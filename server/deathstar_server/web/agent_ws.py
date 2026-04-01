"""WebSocket agent — interactive Claude Code sessions via the Agent SDK."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeSDKClient,
    ClaudeAgentOptions,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from claude_agent_sdk.types import (
    PermissionResultAllow,
    PermissionResultDeny,
    ThinkingBlock,
)

from deathstar_server.errors import AppError
from deathstar_shared.models import WorkflowKind

logger = logging.getLogger(__name__)

agent_ws_router = APIRouter(prefix="/web/api")

_MAX_SESSIONS = 8
_SESSION_TTL_SECONDS = 15 * 60  # 15 minutes


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


@dataclass
class AgentSession:
    conversation_id: str
    repo: str
    branch: str | None
    working_dir: Path
    workflow: WorkflowKind
    client: ClaudeSDKClient
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    permission_future: asyncio.Future | None = None
    websocket: WebSocket | None = None


_sessions: dict[str, AgentSession] = {}

# Maps (repo, branch) -> conversation_id that holds the lock
_branch_locks: dict[tuple[str, str], str] = {}


_BRANCH_NAME_RE = re.compile(r"^[a-zA-Z0-9._/\-]+$")


def _validate_branch_name(branch: str) -> bool:
    """Validate a branch name to prevent injection via crafted branch strings."""
    if not branch or len(branch) > 256:
        return False
    if branch.startswith("-") or branch.startswith("."):
        return False
    if ".." in branch or branch.endswith(".lock"):
        return False
    return bool(_BRANCH_NAME_RE.match(branch))


def _release_session(session: AgentSession) -> None:
    """Release a session's branch lock and remove it from the session map."""
    _sessions.pop(session.conversation_id, None)
    if session.branch:
        lock_key = (session.repo, session.branch)
        if _branch_locks.get(lock_key) == session.conversation_id:
            _branch_locks.pop(lock_key, None)


def get_active_branches() -> dict[tuple[str, str], str]:
    """Return a snapshot of active branch locks for external consumers (e.g. reaper)."""
    return dict(_branch_locks)


def is_branch_active(repo: str, branch: str) -> bool:
    """Check if a branch has an active agent session."""
    lock_holder = _branch_locks.get((repo, branch))
    return lock_holder is not None and lock_holder in _sessions

_AUTH_ERROR_HINTS = (
    "auth", "unauthorized", "unauthenticated", "token", "credential",
    "login", "expired", "403", "401", "permission denied", "not logged in",
    "sign in", "api key",
)


def _is_auth_error(error: Exception) -> bool:
    """Heuristic: check if an SDK/CLI error looks like an auth failure."""
    msg = str(error).lower()
    return any(hint in msg for hint in _AUTH_ERROR_HINTS)


def _claude_agent_env() -> dict[str, str]:
    """Build env dict for Claude CLI/SDK subprocesses.

    API keys have been removed from os.environ at startup (see app_state.py)
    so the subprocess gets a clean environment.  We inject the stored OAuth
    token so the CLI authenticates via subscription.

    Git author/committer is set to a random Star Wars character so commits
    from the agent are attributed to DeathStar, not Claude.
    """
    from deathstar_server.app_state import settings as _settings
    from deathstar_server.services.gitops import _random_star_wars_character
    env = os.environ.copy()
    config_dir = _settings.workspace_root / "deathstar" / ".claude"
    env["CLAUDE_CONFIG_DIR"] = str(config_dir)
    token_path = config_dir / "oauth_token"
    if token_path.is_file():
        token = token_path.read_text().strip()
        if token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = token
            logger.debug("OAuth token loaded (%d chars)", len(token))
        else:
            logger.warning("OAuth token file exists but is empty")
    else:
        logger.debug("No stored OAuth token at %s", token_path)

    # Override git identity so agent commits use Star Wars characters
    character = _random_star_wars_character()
    env["GIT_AUTHOR_NAME"] = character["name"]
    env["GIT_AUTHOR_EMAIL"] = character["email"]
    env["GIT_COMMITTER_NAME"] = character["name"]
    env["GIT_COMMITTER_EMAIL"] = character["email"]

    return env


# JSON settings string passed to ClaudeAgentOptions to disable the
# Co-Authored-By trailer that Claude Code adds to commits/PRs.
_AGENT_SETTINGS_JSON = json.dumps({"attribution": {"commit": "", "pr": ""}})


def _check_claude_auth() -> bool:
    """Quick pre-flight: is the Claude CLI authenticated?"""
    try:
        env = _claude_agent_env()
        result = subprocess.run(
            ["claude", "auth", "status"],
            capture_output=True, text=True, timeout=5, env=env,
        )
        output = (result.stdout + result.stderr).strip()
        authenticated = result.returncode == 0 and "not" not in output.lower()
        logger.info("claude auth status: rc=%d authenticated=%s output=%r", result.returncode, authenticated, output[:200])
        return authenticated
    except Exception as exc:
        logger.error("claude auth status check failed: %s", exc)
        return False


_CLAUDEIGNORE_CONTENT = """\
# Auto-generated by DeathStar to speed up Claude CLI startup
node_modules/
.git/objects/
.git/pack/
dist/
build/
__pycache__/
.venv/
venv/
.next/
.nuxt/
coverage/
.terraform/
*.lock
"""


_PROTECTED_BRANCHES = frozenset({"main", "master"})

# Patterns that indicate a push to a protected branch via Bash tool
_PUSH_TO_PROTECTED_RE = re.compile(
    r"git\s+push\b.*?\b(?:origin\s+)?(?:HEAD:)?("
    + "|".join(_PROTECTED_BRANCHES)
    + r")\b",
)


def _check_protected_branch_push(tool_name: str, tool_input) -> PermissionResultDeny | None:
    """Return a PermissionResultDeny if the tool call would push to a protected branch."""
    if tool_name != "Bash":
        return None
    command = ""
    if isinstance(tool_input, dict):
        command = str(tool_input.get("command", ""))
    elif isinstance(tool_input, str):
        command = tool_input
    if not command:
        return None

    # Block: git push ... main/master
    if _PUSH_TO_PROTECTED_RE.search(command):
        logger.warning("BLOCKED push to protected branch: %s", command[:200])
        return PermissionResultDeny(
            message="Pushing directly to main/master is not allowed. Create a feature branch instead.",
        )

    # Block: git push without explicit branch (could push current branch if it's main)
    # Match "git push" with no branch arg (just "git push" or "git push origin")
    if re.search(r"git\s+push\s*$", command.strip()) or re.search(r"git\s+push\s+origin\s*$", command.strip()):
        logger.warning("BLOCKED ambiguous git push (could push main): %s", command[:200])
        return PermissionResultDeny(
            message="Ambiguous git push — specify a feature branch explicitly. Pushing to main/master is not allowed.",
        )

    # Block: git push --force (to any branch — too dangerous)
    if re.search(r"git\s+push\s+.*--force", command) or re.search(r"git\s+push\s+-f\b", command):
        logger.warning("BLOCKED force push: %s", command[:200])
        return PermissionResultDeny(
            message="Force push is not allowed from DeathStar.",
        )

    return None


def _ensure_claudeignore(repo_root: Path) -> None:
    """Drop a .claudeignore in the repo if one doesn't exist."""
    ignore_path = repo_root / ".claudeignore"
    if not ignore_path.exists():
        try:
            ignore_path.write_text(_CLAUDEIGNORE_CONTENT)
        except OSError:
            pass  # Best-effort


async def _evict_stale_sessions() -> None:
    now = time.time()
    stale = [
        k for k, s in _sessions.items()
        if now - s.last_active > _SESSION_TTL_SECONDS
    ]
    for k in stale:
        session = _sessions.get(k)
        if not session:
            continue
        _release_session(session)
        try:
            await session.client.disconnect()
        except Exception:
            pass
        logger.info("evicted stale agent session %s (branch=%s)", k, session.branch)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def _authenticate(websocket: WebSocket) -> bool:
    from deathstar_server.app_state import settings as _settings
    if not _settings.api_token:
        return True  # No auth configured — allow all
    # Check session cookie first
    from deathstar_server.session import SESSION_COOKIE_NAME, validate_session_token
    cookie = websocket.cookies.get(SESSION_COOKIE_NAME)
    if cookie and validate_session_token(cookie, _settings.api_token):
        return True
    # Fallback: query param token for backward compatibility
    token = websocket.query_params.get("token")
    if token:
        import hmac
        return hmac.compare_digest(token, _settings.api_token)
    return False


# ---------------------------------------------------------------------------
# Build agent options
# ---------------------------------------------------------------------------


def _build_options(
    *,
    workflow: WorkflowKind,
    cwd: str,
    system_prompt: str | None = None,
    model: str | None = None,
    session_id: str | None = None,
    can_use_tool=None,
) -> ClaudeAgentOptions:
    from deathstar_server.services.agent import _MODE_CONFIGS
    cfg = _MODE_CONFIGS.get(workflow, _MODE_CONFIGS[WorkflowKind.PROMPT])

    kwargs: dict = {
        "allowed_tools": cfg["allowed_tools"],
        "permission_mode": cfg["permission_mode"],
        "cwd": cwd,
        "include_partial_messages": True,
        "env": _claude_agent_env(),
        "settings": _AGENT_SETTINGS_JSON,
        "debug_stderr": True,
    }
    max_turns = cfg.get("max_turns")
    if max_turns:
        kwargs["max_turns"] = max_turns
    if system_prompt:
        kwargs["system_prompt"] = system_prompt
    if model:
        kwargs["model"] = model
    if session_id:
        kwargs["resume"] = session_id
    if can_use_tool:
        kwargs["can_use_tool"] = can_use_tool

    return ClaudeAgentOptions(**kwargs)


# ---------------------------------------------------------------------------
# WebSocket helpers
# ---------------------------------------------------------------------------


async def _send(ws: WebSocket, msg_type: str, **data) -> None:
    try:
        await ws.send_json({"type": msg_type, **data})
    except (WebSocketDisconnect, RuntimeError):
        pass


def _usage_dict(usage) -> dict | None:
    if usage is None:
        return None
    if isinstance(usage, dict):
        inp = usage.get("input_tokens") or 0
        out = usage.get("output_tokens") or 0
        return {"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out}
    return None


# ---------------------------------------------------------------------------
# Event forwarding
# ---------------------------------------------------------------------------


async def _forward_events(ws: WebSocket, repo: str | None) -> None:
    """Subscribe to the event bus and forward repo events to a WebSocket client."""
    from deathstar_server.app_state import event_bus

    try:
        async with event_bus.subscribe(repo) as events:
            async for event in events:
                try:
                    await ws.send_json({
                        "type": "repo_event",
                        "event_type": event.event_type,
                        "repo": event.repo,
                        "source": event.source,
                        "data": event.data,
                        "timestamp": event.timestamp,
                    })
                except (WebSocketDisconnect, RuntimeError):
                    break
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.warning("event forwarding error for repo=%s", repo, exc_info=True)


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


@agent_ws_router.websocket("/agent")
async def agent_ws(
    websocket: WebSocket,
):
    """Interactive Claude Code agent session over WebSocket.

    Client-to-server messages:
        {"type": "start", "repo": "...", "message": "...", "workflow": "prompt",
         "conversation_id": "...|null", "model": "...", "system": "..."}
        {"type": "input", "text": "..."}
        {"type": "permission_response", "allow": true|false}
        {"type": "interrupt"}
        {"type": "compact"}

    Server-to-client messages:
        {"type": "text_delta", "text": "..."}
        {"type": "thinking", "text": "..."}
        {"type": "tool_use", "id": "...", "tool": "...", "input": {...}}
        {"type": "tool_result", "tool_use_id": "...", "content": "...", "is_error": false}
        {"type": "permission_request", "tool": "...", "input": {...}}
        {"type": "result", "conversation_id": "...", "message_id": "...",
         "session_id": "...", "model": "...", "duration_ms": ...,
         "usage": {...}, "cost_usd": ..., "content": "...", "status": "..."}
        {"type": "status", "status": "rate_limited", "message": "...",
         "retry_delay_s": 430, "attempt": 1, "max_retries": 10}
        {"type": "error", "code": "...", "message": "..."}
        {"type": "compact_done", "summary": "..."}
    """
    if not _authenticate(websocket):
        await websocket.close(code=4001, reason="unauthorized")
        return

    await _evict_stale_sessions()

    if len(_sessions) >= _MAX_SESSIONS:
        await websocket.close(code=4002, reason="too many agent sessions")
        return

    await websocket.accept()

    session: AgentSession | None = None
    event_forward_task: asyncio.Task | None = None

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send(websocket, "error", code="INVALID_JSON", message="invalid JSON")
                continue

            msg_type = msg.get("type")

            if msg_type == "start":
                session = await _handle_start(websocket, msg, session)

            elif msg_type == "input" and session:
                # Send follow-up message to the running client
                try:
                    follow_up = msg.get("text", "")
                    await session.client.query(follow_up)
                    session.last_active = time.time()
                    # Start a new reader for the follow-up response
                    asyncio.create_task(
                        _read_messages(websocket, session, prompt=follow_up)
                    )
                except Exception as exc:
                    await _send(websocket, "error", code="INTERNAL_ERROR", message=str(exc))

            elif msg_type == "permission_response" and session:
                if session.permission_future and not session.permission_future.done():
                    allow = msg.get("allow", False)
                    if allow:
                        session.permission_future.set_result(
                            PermissionResultAllow()
                        )
                    else:
                        session.permission_future.set_result(
                            PermissionResultDeny(message="User denied via web UI")
                        )

            elif msg_type == "compact" and session:
                try:
                    await session.client.query("/compact")
                    session.last_active = time.time()
                    asyncio.create_task(_read_compact(websocket, session))
                except Exception as exc:
                    logger.warning("compact failed: %s", exc)
                    await _send(websocket, "compact_done", summary="Compact failed")

            elif msg_type == "interrupt" and session:
                try:
                    await session.client.interrupt()
                except Exception:
                    pass

            elif msg_type == "subscribe_events":
                # Start forwarding repo events to this client
                repo = msg.get("repo")
                if not repo:
                    await _send(websocket, "error", code="INVALID_REQUEST", message="repo is required for subscribe_events")
                    continue
                if event_forward_task:
                    event_forward_task.cancel()
                event_forward_task = asyncio.create_task(
                    _forward_events(websocket, repo),
                    name="event-forward",
                )

            else:
                await _send(websocket, "error", code="UNKNOWN_MESSAGE", message=f"unknown message type: {msg_type}")

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("agent_ws error")
    finally:
        # Cancel event forwarding
        if event_forward_task:
            event_forward_task.cancel()
        if session:
            # Release branch lock so another session can use this branch
            _release_session(session)
            try:
                await session.client.disconnect()
            except Exception:
                pass


async def _handle_start(
    websocket: WebSocket,
    msg: dict,
    existing_session: AgentSession | None,
) -> AgentSession | None:
    """Handle a 'start' message — create or reuse an agent session."""
    from deathstar_server.app_state import conversation_store, worktree_manager

    repo = msg.get("repo", "")
    message = msg.get("message", "")
    workflow_str = msg.get("workflow", "prompt")
    conversation_id = msg.get("conversation_id")
    model = msg.get("model")
    system_prompt = msg.get("system")
    auto_accept = msg.get("auto_accept", False)
    branch = msg.get("branch") or None  # Normalize empty string to None

    try:
        workflow = WorkflowKind(workflow_str)
    except ValueError:
        workflow = WorkflowKind.PROMPT

    logger.info(
        "agent start: repo=%s branch=%s workflow=%s conv=%s model=%s",
        repo, branch, workflow_str, conversation_id, model,
    )

    # Validate branch name
    if branch and not _validate_branch_name(branch):
        await _send(
            websocket, "error",
            code="INVALID_REQUEST",
            message=f"Invalid branch name: '{branch}'",
        )
        return existing_session

    # Check branch lock BEFORE creating worktree (issue 5)
    if branch:
        lock_key = (repo, branch)
        holder = _branch_locks.get(lock_key)
        if holder and holder != conversation_id and holder in _sessions:
            await _send(
                websocket, "error",
                code="BRANCH_LOCKED",
                message=f"Branch '{branch}' is already in use by another session.",
            )
            return existing_session
        # Register lock immediately to prevent races (issue 8)
        _branch_locks[lock_key] = conversation_id or "__pending__"

    # Resolve working directory via worktree manager
    try:
        cwd = worktree_manager.resolve_working_dir(repo, branch)
    except AppError as exc:
        # Release the lock we just acquired since we can't proceed
        if branch:
            _branch_locks.pop((repo, branch), None)
        await _send(
            websocket, "error",
            code="WORKTREE_ERROR",
            message=f"Failed to resolve working directory: {exc.message}",
        )
        return existing_session

    logger.info("resolved working dir: %s (branch=%s)", cwd, branch)

    # Ensure .claudeignore exists in the working directory
    _ensure_claudeignore(cwd)

    # Get or create conversation
    conversation_id = conversation_store.get_or_create(conversation_id, repo, branch)
    conversation_store.add_user_message(conversation_id, message)

    # Update branch lock with real conversation_id
    if branch:
        _branch_locks[(repo, branch)] = conversation_id

    # Look up existing SDK session ID for multi-turn continuity
    sdk_session_id = conversation_store.get_session_id(conversation_id)

    # Check if we can reuse an existing session
    session = existing_session
    if session and session.conversation_id == conversation_id:
        # Reuse existing ClaudeSDKClient — just send a new query
        session.last_active = time.time()
        session.websocket = websocket
        session.workflow = workflow
    else:
        # Pre-flight auth check before creating a new client
        if not _check_claude_auth():
            if branch:
                _branch_locks.pop((repo, branch), None)
            await _send(
                websocket, "error",
                code="AUTH_REQUIRED",
                message="Claude is not authenticated. Open the Claude menu in the top bar to connect your account.",
            )
            return None

        # Create a new ClaudeSDKClient
        if existing_session:
            _release_session(existing_session)
            try:
                await existing_session.client.disconnect()
            except Exception:
                pass

        # Build permission callback bound to this session
        session_ref: AgentSession | None = None  # Will be set after creation

        if auto_accept:
            async def can_use_tool(tool_name, tool_input, context):
                # Hard block: never allow pushing to protected branches
                deny = _check_protected_branch_push(tool_name, tool_input)
                if deny:
                    return deny
                logger.info("auto-accepting tool: %s", tool_name)
                return PermissionResultAllow()
        else:
            async def can_use_tool(tool_name, tool_input, context):
                # Hard block: never allow pushing to protected branches
                deny = _check_protected_branch_push(tool_name, tool_input)
                if deny:
                    return deny

                s = session_ref
                if not s or not s.websocket:
                    return PermissionResultDeny(message="No active WebSocket")

                await _send(s.websocket, "permission_request", tool=tool_name, input=tool_input)
                s.permission_future = asyncio.get_event_loop().create_future()
                try:
                    result = await asyncio.wait_for(s.permission_future, timeout=120)
                except asyncio.TimeoutError:
                    return PermissionResultDeny(message="Permission request timed out")
                finally:
                    s.permission_future = None
                return result

        options = _build_options(
            workflow=workflow,
            cwd=str(cwd),
            system_prompt=system_prompt,
            model=model,
            session_id=sdk_session_id,
            can_use_tool=can_use_tool,
        )

        logger.info("creating ClaudeSDKClient with cwd=%s, workflow=%s", cwd, workflow)
        client = ClaudeSDKClient(options=options)
        try:
            logger.info("connecting ClaudeSDKClient...")
            await client.connect()
            logger.info("ClaudeSDKClient connected successfully")
        except Exception as exc:
            error_code = "AUTH_EXPIRED" if _is_auth_error(exc) else "SDK_ERROR"
            error_msg = (
                "Claude authentication has expired. Open the Claude menu in the top bar to reconnect."
                if _is_auth_error(exc)
                else f"Failed to start Claude agent: {exc}"
            )
            logger.error("ClaudeSDKClient.connect() failed: %s", exc, exc_info=True)
            if branch:
                _branch_locks.pop((repo, branch), None)
            await _send(websocket, "error", code=error_code, message=error_msg)
            return None

        session = AgentSession(
            conversation_id=conversation_id,
            repo=repo,
            branch=branch,
            working_dir=cwd,
            workflow=workflow,
            client=client,
            websocket=websocket,
        )
        session_ref = session
        _sessions[conversation_id] = session

    # Send the query
    try:
        logger.info("sending query: %s... (conv=%s)", message[:80], conversation_id)
        await session.client.query(message)
        logger.info("query sent successfully")
    except Exception as exc:
        error_code = "AUTH_EXPIRED" if _is_auth_error(exc) else "SDK_ERROR"
        error_msg = (
            "Claude authentication has expired. Open the Claude menu in the top bar to reconnect."
            if _is_auth_error(exc)
            else str(exc)
        )
        await _send(websocket, "error", code=error_code, message=error_msg)
        return session

    # Notify the client we've started
    await _send(websocket, "started", conversation_id=conversation_id)

    # Read messages in the background
    asyncio.create_task(_read_messages(websocket, session, prompt=message))

    return session


def _generate_branch_name(prompt: str) -> str:
    """Generate a branch name from the user's prompt."""
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")
    slug = slug[:40] or "change"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"deathstar/{timestamp}-{slug}"


def _agent_already_opened_pr(text: str, blocks: list[dict]) -> bool:
    """Detect whether the agent already created a pull request.

    Checks for:
    - GitHub PR URLs in the agent's text output
    - ``gh pr create`` in Bash tool calls
    """
    # Check accumulated text for PR URLs
    if re.search(r"https://github\.com/[^/]+/[^/]+/pull/\d+", text):
        return True
    # Check tool calls for gh pr create
    for block in blocks:
        if block.get("type") == "tool_use" and block.get("tool") == "Bash":
            inp = block.get("input", "")
            if isinstance(inp, dict):
                inp = inp.get("command", "")
            if "gh pr create" in str(inp):
                return True
    return False


async def _post_agent_open_pr(
    websocket: WebSocket,
    session: AgentSession,
    prompt: str,
) -> None:
    """After a PR-workflow agent run, commit changes and open a GitHub PR.

    Handles two cases:
    1. Agent left uncommitted changes → we commit, create a branch, push, open PR.
    2. Agent already committed (and possibly pushed) → we push the current
       branch if needed and open a PR from it.
    """
    from deathstar_server.app_state import git_service, github_service

    repo_root = session.working_dir
    current = git_service.current_branch(repo_root)
    has_uncommitted = git_service.has_uncommitted_changes(repo_root)

    # Check if the agent made any commits vs the remote base
    agent_committed = False
    if not has_uncommitted:
        try:
            # See if there are local commits not on origin/main
            result = subprocess.run(
                ["git", "log", "origin/main..HEAD", "--oneline"],
                cwd=str(repo_root), capture_output=True, text=True, check=True,
            )
            agent_committed = bool(result.stdout.strip())
        except subprocess.CalledProcessError:
            pass

    if not has_uncommitted and not agent_committed:
        await _send(websocket, "text_delta", text="\n\n*No changes detected — skipping PR creation.*")
        return

    await _send(websocket, "text_delta", text="\n\n---\n*Creating pull request...*\n")

    try:
        github_service.ensure_remote_origin(repo_root)

        if has_uncommitted:
            # Case 1: Agent left uncommitted changes — we handle the git workflow
            branch = _generate_branch_name(prompt)
            git_service.ensure_branch(repo_root, branch)
            commit_msg = f"deathstar: {prompt[:80]}"
            git_service.commit_all(repo_root, commit_msg)
            await _send(websocket, "text_delta", text=f"Committed to `{branch}`. Pushing...")
            github_service.push_branch(repo_root, branch)
        else:
            # Case 2: Agent already committed — use the current branch
            branch = current
            # Push if needed (agent may or may not have pushed)
            try:
                result = subprocess.run(
                    ["git", "log", f"origin/{branch}..HEAD", "--oneline"],
                    cwd=str(repo_root), capture_output=True, text=True, check=True,
                )
                if result.stdout.strip():
                    await _send(websocket, "text_delta", text=f"Pushing `{branch}`...")
                    github_service.push_branch(repo_root, branch)
                else:
                    await _send(websocket, "text_delta", text=f"Branch `{branch}` already pushed.")
            except subprocess.CalledProcessError:
                # Remote tracking branch may not exist yet — push it
                await _send(websocket, "text_delta", text=f"Pushing `{branch}`...")
                github_service.push_branch(repo_root, branch)

        await _send(websocket, "text_delta", text=" Opening PR...")

        # Determine base branch (usually main)
        base_branch = "main"
        try:
            result = subprocess.run(
                ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
                cwd=str(repo_root), capture_output=True, text=True, check=True,
            )
            base_branch = result.stdout.strip().rsplit("/", 1)[-1]
        except subprocess.CalledProcessError:
            pass  # Default to "main"

        pr_url = await github_service.create_pull_request(
            repo_root=repo_root,
            title=prompt[:120],
            body=f"Generated by DeathStar agent.\n\n**Prompt:** {prompt}",
            head_branch=branch,
            base_branch=base_branch,
            draft=False,
        )
        await _send(websocket, "text_delta", text=f"\n\nPR opened: {pr_url}")
        logger.info("PR created: %s (conv=%s)", pr_url, session.conversation_id)

    except Exception as exc:
        logger.exception("post-agent PR creation failed: %s", exc)
        await _send(
            websocket, "text_delta",
            text=f"\n\n*PR creation failed: {exc}*",
        )


async def _read_compact(websocket: WebSocket, session: AgentSession) -> None:
    """Read compact result silently — don't save to conversation store."""
    try:
        async for message in session.client.receive_messages():
            session.last_active = time.time()
            if isinstance(message, ResultMessage):
                summary = message.result or "Context compacted successfully"
                await _send(websocket, "compact_done", summary=summary)
                return
        # Loop ended without ResultMessage
        await _send(websocket, "compact_done", summary="Context compacted")
    except Exception as exc:
        logger.warning("compact read error: %s", exc)
        await _send(websocket, "compact_done", summary="Compact completed")


async def _read_messages(websocket: WebSocket, session: AgentSession, *, prompt: str = "") -> None:
    """Read messages from the SDK client and forward to the WebSocket."""
    from deathstar_server.app_state import conversation_store

    started = time.perf_counter()
    accumulated_text = ""
    # Track text sent to WS via stream deltas so AssistantMessage blocks
    # never re-send what was already streamed (fixes duplicate messages).
    delta_sent_text = ""
    accumulated_blocks: list[dict] = []
    msg_count = 0

    logger.info("_read_messages started for conv=%s", session.conversation_id)

    try:
        async for message in session.client.receive_messages():
            msg_count += 1
            session.last_active = time.time()
            logger.info(
                "recv message #%d type=%s (conv=%s, elapsed=%.1fs)",
                msg_count, type(message).__name__, session.conversation_id,
                time.perf_counter() - started,
            )

            if isinstance(message, AssistantMessage):
                logger.info("  AssistantMessage blocks: %s", [type(b).__name__ for b in message.content])
                for block in message.content:
                    if isinstance(block, TextBlock):
                        # Stream deltas already delivered this text to the
                        # WebSocket.  Only send from AssistantMessage if the
                        # text was genuinely NOT seen via deltas (e.g. SDK
                        # skipped streaming).  The previous `endswith` check
                        # broke when multiple text blocks existed in a turn.
                        already_sent = (
                            block.text in delta_sent_text
                            or block.text in accumulated_text
                        )
                        if not already_sent:
                            accumulated_text += block.text
                            await _send(websocket, "text_delta", text=block.text)
                        elif not accumulated_text.endswith(block.text) and block.text not in accumulated_text:
                            accumulated_text += block.text
                        # Track in blocks for DB storage
                        if accumulated_blocks and accumulated_blocks[-1].get("type") == "text":
                            if block.text not in accumulated_blocks[-1]["text"]:
                                accumulated_blocks[-1]["text"] += block.text
                        else:
                            if not any(b.get("type") == "text" and block.text in b["text"] for b in accumulated_blocks):
                                accumulated_blocks.append({"type": "text", "text": block.text})
                    elif isinstance(block, ToolUseBlock):
                        logger.info("  ToolUse: %s", block.name)
                        accumulated_blocks.append({
                            "type": "tool_use", "id": block.id,
                            "tool": block.name, "input": block.input,
                        })
                        await _send(
                            websocket, "tool_use",
                            id=block.id, tool=block.name, input=block.input,
                        )
                    elif isinstance(block, ToolResultBlock):
                        content = block.content
                        if isinstance(content, list):
                            content = "\n".join(
                                item.get("text", str(item))
                                for item in content
                                if isinstance(item, dict)
                            )
                        logger.info("  ToolResult: id=%s is_error=%s len=%d", block.tool_use_id, block.is_error, len(str(content or "")))
                        result_str = str(content or "")
                        accumulated_blocks.append({
                            "type": "tool_result", "toolUseId": block.tool_use_id,
                            "content": result_str[:2000],  # Cap size for DB storage
                            "isError": block.is_error or False,
                        })
                        await _send(
                            websocket, "tool_result",
                            tool_use_id=block.tool_use_id,
                            content=result_str,
                            is_error=block.is_error or False,
                        )
                    elif isinstance(block, ThinkingBlock):
                        # Merge consecutive thinking blocks for DB storage only.
                        # Don't send a WS event — thinking_delta StreamEvents
                        # already streamed this text incrementally, so sending
                        # the full block again would cause a duplicate in the UI.
                        if accumulated_blocks and accumulated_blocks[-1].get("type") == "thinking":
                            accumulated_blocks[-1]["text"] += block.thinking
                        else:
                            accumulated_blocks.append({"type": "thinking", "text": block.thinking})

            elif isinstance(message, StreamEvent):
                event_data = message.event
                event_type = event_data.get("type", "")
                if msg_count <= 5 or event_type != "content_block_delta":
                    logger.debug("  StreamEvent: %s", event_type)
                if event_type == "content_block_delta":
                    delta = event_data.get("delta", {})
                    if delta.get("type") == "text_delta":
                        text = delta.get("text", "")
                        if text:
                            accumulated_text += text
                            delta_sent_text += text
                            # Merge into last text block
                            if accumulated_blocks and accumulated_blocks[-1].get("type") == "text":
                                accumulated_blocks[-1]["text"] += text
                            else:
                                accumulated_blocks.append({"type": "text", "text": text})
                            await _send(websocket, "text_delta", text=text)
                    elif delta.get("type") == "thinking_delta":
                        text = delta.get("thinking", "")
                        if text:
                            # Merge into last thinking block
                            if accumulated_blocks and accumulated_blocks[-1].get("type") == "thinking":
                                accumulated_blocks[-1]["text"] += text
                            else:
                                accumulated_blocks.append({"type": "thinking", "text": text})
                            await _send(websocket, "thinking_delta", text=text)

            elif isinstance(message, ResultMessage):
                duration_ms = int((time.perf_counter() - started) * 1000)
                final_text = accumulated_text or message.result or ""

                logger.info(
                    "ResultMessage: session_id=%s is_error=%s turns=%s cost=$%s text_len=%d (conv=%s)",
                    message.session_id, message.is_error, message.num_turns,
                    message.total_cost_usd, len(final_text), session.conversation_id,
                )

                # If a resumed session fails almost instantly, the session is
                # likely stale (e.g. auth method changed). Clear the stored
                # session ID so the next attempt starts fresh.
                if message.is_error and duration_ms < 5000 and (message.num_turns or 0) <= 1:
                    logger.warning(
                        "resumed session failed quickly (%dms) — clearing stale session_id for conv=%s",
                        duration_ms, session.conversation_id,
                    )
                    conversation_store.update_session_id(session.conversation_id, None)
                    # Also tear down the cached client so next request builds a new one
                    _release_session(session)
                    try:
                        await session.client.disconnect()
                    except Exception:
                        pass
                elif message.session_id:
                    conversation_store.update_session_id(
                        session.conversation_id, message.session_id
                    )

                # PR post-processing: commit, push, open PR
                # Skip if the agent already created a PR (detected via tool
                # calls or PR URLs in the output).
                if session.workflow == WorkflowKind.PR and not message.is_error:
                    if _agent_already_opened_pr(accumulated_text, accumulated_blocks):
                        logger.info("agent already opened a PR — skipping post-processing")
                    else:
                        await _post_agent_open_pr(websocket, session, prompt)

                msg_id = conversation_store.add_assistant_message(
                    session.conversation_id,
                    final_text,
                    workflow=session.workflow,
                    provider="anthropic",
                    model="claude",
                    duration_ms=duration_ms,
                    agent_blocks=accumulated_blocks or None,
                )

                await _send(
                    websocket, "result",
                    conversation_id=session.conversation_id,
                    message_id=msg_id,
                    session_id=message.session_id,
                    model="claude",
                    duration_ms=duration_ms,
                    num_turns=message.num_turns,
                    usage=_usage_dict(message.usage),
                    cost_usd=message.total_cost_usd,
                    content=final_text,
                    status="failed" if message.is_error else "succeeded",
                )
                break  # ResultMessage is terminal

            elif isinstance(message, SystemMessage):
                subtype = getattr(message, "subtype", "")
                data = getattr(message, "data", {}) or {}
                if subtype == "api_retry":
                    delay_ms = data.get("retry_delay_ms", 0)
                    attempt = data.get("attempt", 0)
                    max_retries = data.get("max_retries", 0)
                    error = data.get("error", "rate_limit")
                    delay_s = delay_ms // 1000
                    logger.warning(
                        "api_retry: attempt=%d/%d delay=%ds error=%s (conv=%s)",
                        attempt, max_retries, delay_s, error, session.conversation_id,
                    )
                    await _send(
                        websocket, "status",
                        status="rate_limited",
                        message=f"Rate limited — retrying in {delay_s}s (attempt {attempt}/{max_retries})",
                        retry_delay_s=delay_s,
                        attempt=attempt,
                        max_retries=max_retries,
                    )
                else:
                    logger.info("  SystemMessage subtype=%s", subtype)

            else:
                logger.warning("  Unknown message type: %s — %r", type(message).__name__, str(message)[:200])

        logger.info("_read_messages loop ended: %d messages, %.1fs (conv=%s)", msg_count, time.perf_counter() - started, session.conversation_id)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected during _read_messages (conv=%s, %d messages)", session.conversation_id, msg_count)
    except Exception as exc:
        logger.exception("agent message reader error after %d messages: %s", msg_count, exc)
        try:
            error_code = "AUTH_EXPIRED" if _is_auth_error(exc) else "INTERNAL_ERROR"
            error_msg = (
                "Claude authentication has expired. Open the Claude menu in the top bar to reconnect."
                if _is_auth_error(exc)
                else str(exc)
            )
            await _send(websocket, "error", code=error_code, message=error_msg)
        except Exception:
            pass
