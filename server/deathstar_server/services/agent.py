"""Claude Agent SDK integration for the web UI chat pipeline."""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

from deathstar_shared.models import WorkflowKind

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-mode agent configuration
# ---------------------------------------------------------------------------

# Plugins loaded for every mode (hook-based, only fires on write tools)
_BASE_PLUGINS = ["security-guidance"]

_MODE_CONFIGS: dict[WorkflowKind, dict] = {
    WorkflowKind.PROMPT: {
        "allowed_tools": ["Read", "Glob", "Grep", "WebSearch", "WebFetch"],
        "permission_mode": "default",
        "max_turns": 30,
    },
    WorkflowKind.PATCH: {
        "allowed_tools": ["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
        "permission_mode": "acceptEdits",
        "plugins": ["deathstar-code", "frontend-design"],
    },
    WorkflowKind.PR: {
        "allowed_tools": ["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
        "permission_mode": "acceptEdits",
        "plugins": ["deathstar-code", "frontend-design", "feature-dev"],
    },
    WorkflowKind.REVIEW: {
        "allowed_tools": ["Read", "Glob", "Grep", "Bash", "Agent"],
        "permission_mode": "default",
        "plugins": ["deathstar-review", "code-review", "pr-review-toolkit"],
        "max_turns": 50,
    },
    WorkflowKind.DOCS: {
        "allowed_tools": ["Read", "Write", "Edit", "Glob", "Grep"],
        "permission_mode": "acceptEdits",
        "plugins": ["deathstar-docs", "frontend-design"],
        "max_turns": 50,
    },
    WorkflowKind.AUDIT: {
        "allowed_tools": ["Read", "Glob", "Grep", "Bash"],
        "permission_mode": "default",
        "plugins": ["deathstar-audit"],
        "max_turns": 50,
    },
    WorkflowKind.PLAN: {
        "allowed_tools": ["Read", "Glob", "Grep"],
        "permission_mode": "default",
        "plugins": ["deathstar-plan"],
        "max_turns": 30,
    },
}


# ---------------------------------------------------------------------------
# Plugin discovery
# ---------------------------------------------------------------------------

_PLUGIN_MARKETPLACE = "claude-plugins-official"
_PLUGIN_REPO_URL = "https://github.com/anthropics/claude-plugins-official.git"

_PLUGIN_SEARCH_DIRS = [
    # Pre-installed in Docker image (baked in at build time)
    Path("/opt/claude-plugins"),
    # Home-based Claude config (local dev)
    Path.home() / ".claude" / "plugins" / "marketplaces" / _PLUGIN_MARKETPLACE / "plugins",
    # Container / workspace-based
    Path("/workspace/deathstar/.claude/plugins/marketplaces") / _PLUGIN_MARKETPLACE / "plugins",
]

# All plugins that should be available at runtime
_REQUIRED_PLUGINS = [
    # Official Anthropic plugins
    "security-guidance", "code-review", "pr-review-toolkit",
    "frontend-design", "feature-dev",
    # Custom DeathStar skill plugins
    "deathstar-audit", "deathstar-review", "deathstar-plan",
    "deathstar-docs", "deathstar-code",
]

_plugins_checked = False


_CUSTOM_PLUGINS = {"deathstar-audit", "deathstar-review", "deathstar-plan", "deathstar-docs", "deathstar-code"}

# Possible locations of the repo's plugins/ directory (for custom plugins)
_REPO_PLUGIN_DIRS = [
    Path("/opt/deathstar/repo/plugins"),       # Production (redeploy copies repo here)
    Path(__file__).resolve().parents[3] / "plugins",  # Local dev (relative to agent.py)
]


def _ensure_plugins() -> None:
    """Auto-install missing plugins from the official repo and local repo (runs once)."""
    global _plugins_checked
    if _plugins_checked:
        return
    _plugins_checked = True

    missing = [name for name in _REQUIRED_PLUGINS if _find_plugin(name) is None]
    if not missing:
        return

    # Pick an install target: CLAUDE_PLUGIN_DIR, then /opt/claude-plugins, then workspace
    env_dir = os.environ.get("CLAUDE_PLUGIN_DIR")
    target = Path(env_dir) if env_dir else Path("/opt/claude-plugins")
    if not _can_write(target):
        target = Path("/workspace/deathstar/.claude/plugins/marketplaces") / _PLUGIN_MARKETPLACE / "plugins"
    if not _can_write(target):
        logger.warning("cannot install plugins — no writable directory found")
        return

    target.mkdir(parents=True, exist_ok=True)
    import shutil

    # Install custom deathstar plugins from the repo
    custom_missing = [n for n in missing if n in _CUSTOM_PLUGINS]
    if custom_missing:
        for repo_dir in _REPO_PLUGIN_DIRS:
            if not repo_dir.is_dir():
                continue
            for name in list(custom_missing):
                plugin_src = repo_dir / name
                if plugin_src.is_dir():
                    dest = target / name
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(plugin_src, dest)
                    logger.info("installed custom plugin %s → %s", name, dest)
                    custom_missing.remove(name)
            if not custom_missing:
                break

    # Install official plugins from GitHub
    official_missing = [n for n in missing if n not in _CUSTOM_PLUGINS and _find_plugin(n) is None]
    if official_missing:
        logger.info("auto-installing %d official plugins to %s: %s", len(official_missing), target, official_missing)
        try:
            import subprocess
            result = subprocess.run(
                ["git", "clone", "--depth=1", _PLUGIN_REPO_URL, "/tmp/_claude-plugins-src"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                logger.warning("failed to clone plugin repo: %s", result.stderr.strip())
                return
            src = Path("/tmp/_claude-plugins-src/plugins")
            for name in official_missing:
                plugin_src = src / name
                if plugin_src.is_dir():
                    dest = target / name
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(plugin_src, dest)
                    logger.info("installed plugin %s → %s", name, dest)
                else:
                    logger.warning("plugin %s not found in cloned repo", name)
            shutil.rmtree("/tmp/_claude-plugins-src", ignore_errors=True)
        except Exception as exc:
            logger.warning("auto-install of official plugins failed: %s", exc)


def _can_write(path: Path) -> bool:
    """Check if we can write to a directory (or its parent)."""
    try:
        check = path if path.exists() else path.parent
        return os.access(check, os.W_OK)
    except OSError:
        return False


def _find_plugin(name: str) -> Path | None:
    """Find a Claude plugin directory by name."""
    # Check CLAUDE_PLUGIN_DIR env override first
    env_dir = os.environ.get("CLAUDE_PLUGIN_DIR")
    if env_dir:
        candidate = Path(env_dir) / name
        if candidate.is_dir():
            return candidate

    for search_dir in _PLUGIN_SEARCH_DIRS:
        candidate = search_dir / name
        if candidate.is_dir():
            return candidate
    return None


def _resolve_plugins(plugin_names: list[str]) -> list[dict]:
    """Resolve plugin names to SdkPluginConfig dicts."""
    plugins = []
    for name in plugin_names:
        path = _find_plugin(name)
        if path:
            plugins.append({"type": "local", "path": str(path)})
            logger.info("resolved plugin %s → %s", name, path)
        else:
            logger.warning("plugin %s not found in any search directory", name)
    return plugins


def build_options(
    *,
    workflow: WorkflowKind,
    cwd: Path,
    system_prompt: str | None = None,
    model: str | None = None,
    session_id: str | None = None,
) -> ClaudeAgentOptions:
    """Build ``ClaudeAgentOptions`` for the given workflow mode."""
    _ensure_plugins()
    cfg = _MODE_CONFIGS.get(workflow, _MODE_CONFIGS[WorkflowKind.PROMPT])

    kwargs: dict = {
        "allowed_tools": cfg["allowed_tools"],
        "permission_mode": cfg["permission_mode"],
        "cwd": str(cwd),
    }
    max_turns = cfg.get("max_turns")
    if max_turns:
        kwargs["max_turns"] = max_turns

    # Resolve plugins: base (security-guidance) + per-mode
    plugin_names = list(_BASE_PLUGINS) + cfg.get("plugins", [])
    plugins = _resolve_plugins(plugin_names)
    if plugins:
        kwargs["plugins"] = plugins

    if system_prompt:
        kwargs["system_prompt"] = system_prompt
    if model:
        kwargs["model"] = model
    if session_id:
        kwargs["resume"] = session_id

    return ClaudeAgentOptions(**kwargs)


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------

def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ---------------------------------------------------------------------------
# Streaming wrapper
# ---------------------------------------------------------------------------

async def run_agent_stream(
    *,
    prompt: str,
    options: ClaudeAgentOptions,
    conversation_id: str,
    workflow: WorkflowKind,
) -> AsyncIterator[str]:
    """Run the Claude Agent SDK and yield SSE-formatted events.

    Yields ``delta``, ``progress``, ``done``, and ``error`` events in the
    same format as the existing ``/chat/stream`` endpoint.
    """
    started = time.perf_counter()
    accumulated_text = ""
    session_id: str | None = None
    result_message: ResultMessage | None = None
    last_model: str | None = None

    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                if message.model:
                    last_model = message.model
                for block in message.content:
                    if isinstance(block, TextBlock):
                        accumulated_text += block.text
                        yield _sse("delta", {"text": block.text})
                    elif isinstance(block, ToolUseBlock):
                        yield _sse("progress", {"message": f"Using {block.name}..."})

            elif isinstance(message, ResultMessage):
                result_message = message
                session_id = message.session_id

        duration_ms = int((time.perf_counter() - started) * 1000)

        # Build usage dict from result
        usage_dict = None
        if result_message and result_message.usage:
            raw = result_message.usage
            if isinstance(raw, dict):
                inp = raw.get("input_tokens") or 0
                out = raw.get("output_tokens") or 0
                usage_dict = {"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out}

        cost_usd = result_message.total_cost_usd if result_message else None
        is_error = result_message.is_error if result_message else False

        model = last_model or "claude"

        yield _sse("done", {
            "conversation_id": conversation_id,
            "message_id": "",  # Filled in by the route handler
            "content": accumulated_text,
            "workflow": workflow.value if hasattr(workflow, "value") else str(workflow),
            "provider": "anthropic",
            "model": model,
            "duration_ms": duration_ms,
            "usage": usage_dict,
            "cost_usd": cost_usd,
            "session_id": session_id,
            "status": "failed" if is_error else "succeeded",
        })

    except Exception as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.exception("agent stream error: %s", exc)
        yield _sse("error", {
            "conversation_id": conversation_id,
            "code": "INTERNAL_ERROR",
            "message": str(exc),
            "status": "failed",
        })
