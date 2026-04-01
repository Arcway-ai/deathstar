from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from deathstar_server.app_state import event_bus, git_service, settings
from deathstar_server.errors import AppError
from deathstar_server.services.event_bus import (
    EVENT_BRANCH_UPDATE,
    EVENT_LOCAL_CHECKOUT,
    EVENT_LOCAL_COMMIT,
    RepoEvent,
    SOURCE_LOCAL,
)
from deathstar_shared.models import (
    ApplySuggestionsRequest,
    ApplySuggestionsResponse,
    BranchRequest,
    CheckoutRequest,
    CloneRequest,
    ConversationDetail,
    ConversationSummary,
    ErrorCode,
    FeedbackRequest,
    FeedbackResponse,
    GitHubPullRequestSummary,
    GitHubRepoInfo,
    MemoryEntryResponse,
    PostReviewRequest,
    RepoContextResponse,
    EnqueueRequest,
    QueueItemResponse,
    RepoInfo,
    SaveMemoryRequest,
)

logger = logging.getLogger(__name__)

web_router = APIRouter(prefix="/web/api")


# ---------------------------------------------------------------------------
# Session cookie (for Vite dev mode — production sets cookie via index.html)
# ---------------------------------------------------------------------------


@web_router.post("/auth/session")
def init_session(request: Request):
    """Issue a session cookie.

    When ``api_token`` is configured, requires a valid ``Authorization: Bearer``
    header (one-time bootstrap).  When no ``api_token`` is set, always succeeds.
    In production, the cookie is set when the server serves ``index.html`` so
    the frontend never needs to call this.
    """
    import hmac as _hmac
    from deathstar_server.session import cookie_params, generate_session_token

    api_token = settings.api_token
    if api_token:
        auth_header = request.headers.get("authorization", "")
        bearer = auth_header[7:] if auth_header.startswith("Bearer ") else ""
        if not bearer or not _hmac.compare_digest(bearer, api_token):
            return JSONResponse(status_code=401, content={"message": "unauthorized"})

    resp = JSONResponse(content={"ok": True})
    if api_token:
        token = generate_session_token(api_token)
        params = cookie_params(is_https=request.url.scheme == "https")
        resp.set_cookie(value=token, **params)
    return resp


def _get_conversation_store():
    from deathstar_server.app_state import conversation_store
    return conversation_store


def _get_memory_bank():
    from deathstar_server.app_state import memory_bank
    return memory_bank


def _get_feedback_store():
    from deathstar_server.app_state import feedback_store
    return feedback_store


# ---------------------------------------------------------------------------
# Repos
# ---------------------------------------------------------------------------


@web_router.get("/repos", response_model=list[RepoInfo])
def list_repos() -> list[RepoInfo]:
    projects = settings.projects_root
    if not projects.is_dir():
        return []

    repos: list[RepoInfo] = []
    for entry in sorted(projects.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        git_dir = entry / ".git"
        if not git_dir.exists():
            continue
        try:
            branch = git_service.current_branch(entry)
            dirty = git_service.has_uncommitted_changes(entry)
        except AppError:
            branch = "unknown"
            dirty = False
        repos.append(RepoInfo(name=entry.name, branch=branch, dirty=dirty))
    return repos


@web_router.get("/repos/{name}/tree")
def repo_tree(name: str) -> list[str]:
    target = git_service.resolve_target(name)
    files = list(git_service.select_files(target, max_files=200))
    return [str(f.relative_to(target)) for f in files]


@web_router.get("/repos/{name}/file")
def repo_file(name: str, path: str = Query(..., min_length=1)) -> dict[str, str]:
    # Block access to .git internals (tokens, hooks, etc.)
    path_parts = path.replace("\\", "/").split("/")
    if ".git" in path_parts or any(p.startswith(".git/") or p == ".git" for p in path_parts):
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "access to .git directory is not allowed",
            status_code=403,
        )
    repo_root = git_service.resolve_target(name)
    file_path = (repo_root / path).resolve()
    if not file_path.is_relative_to(repo_root):
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "path escapes the repo root",
            status_code=400,
        )
    content = git_service.read_text(file_path, max_chars_per_file=50_000)
    if content is None:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "file not found or not readable",
            status_code=404,
        )
    return {"path": path, "content": content}


def _detect_default_branch(repo_root: Path) -> str:
    """Detect the default branch (main or master) for a repo."""
    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip().removeprefix("refs/remotes/origin/")
    except subprocess.CalledProcessError:
        pass
    # Fallback: check if main exists, else master
    for candidate in ("main", "master"):
        check = subprocess.run(
            ["git", "rev-parse", "--verify", candidate],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        if check.returncode == 0:
            return candidate
    return "main"


@web_router.get("/repos/{name}/context", response_model=RepoContextResponse)
def repo_context(name: str) -> RepoContextResponse:
    """Return repo context for LLM enrichment: branch, commits, CLAUDE.md, file tree."""
    repo_root = git_service.resolve_target(name)

    # Ensure remote origin is HTTPS-based for push compatibility
    try:
        from deathstar_server.app_state import github_service
        github_service.ensure_remote_origin(repo_root)
    except Exception:
        pass  # Best-effort — don't block context loading

    # Fetch with prune to detect deleted remote branches
    try:
        subprocess.run(
            ["git", "fetch", "--prune"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass  # Best-effort

    # Branch
    branch_switched_from: str | None = None
    try:
        branch = git_service.current_branch(repo_root)
    except AppError:
        branch = "unknown"

    # Detect if the current branch's remote tracking branch was deleted
    # (e.g. after a PR merge on GitHub)
    if branch not in ("main", "master", "unknown"):
        try:
            tracking = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=False,
            )
            # If the upstream is gone, tracking fails or returns empty
            if tracking.returncode != 0:
                # Confirm the branch previously had a remote (not a purely local branch)
                remote_check = subprocess.run(
                    ["git", "config", f"branch.{branch}.remote"],
                    cwd=str(repo_root),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if remote_check.returncode == 0 and remote_check.stdout.strip():
                    # Remote tracking existed but upstream branch is gone — switch to default
                    default_branch = _detect_default_branch(repo_root)
                    logger.info(
                        "branch %s remote tracking gone — switching to %s",
                        branch, default_branch,
                    )
                    branch_switched_from = branch
                    try:
                        subprocess.run(
                            ["git", "checkout", default_branch],
                            cwd=str(repo_root),
                            capture_output=True,
                            text=True,
                            check=True,
                        )
                        subprocess.run(
                            ["git", "pull", "--ff-only"],
                            cwd=str(repo_root),
                            capture_output=True,
                            text=True,
                            check=False,
                            timeout=30,
                        )
                        # Clean up the stale local branch
                        subprocess.run(
                            ["git", "branch", "-D", branch],
                            cwd=str(repo_root),
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                        branch = default_branch
                    except subprocess.CalledProcessError:
                        branch_switched_from = None  # Switch failed, stay put
        except Exception:
            pass  # Best-effort detection

    # Recent commits (last 5)
    recent_commits: list[str] = []
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-5"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
        recent_commits = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # CLAUDE.md
    claude_md: str | None = None
    claude_path = repo_root / "CLAUDE.md"
    if claude_path.is_file():
        try:
            raw = claude_path.read_text(encoding="utf-8")
            # Cap at ~3000 chars to keep token budget reasonable
            claude_md = raw[:3000]
            if len(raw) > 3000:
                claude_md += "\n\n[... truncated]"
        except OSError:
            pass

    # File tree (top-level summary, up to 50 entries)
    file_tree: list[str] = []
    try:
        files = list(git_service.select_files(repo_root, max_files=50))
        file_tree = [str(f.relative_to(repo_root)) for f in files]
    except AppError:
        pass

    # Merge/rebase conflict detection — check both active merge state and
    # unmerged paths (git ls-files -u lists files with unresolved conflicts)
    conflict_files: list[str] = []
    try:
        result = subprocess.run(
            ["git", "ls-files", "-u", "--error-unmatch"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        if result.stdout.strip():
            # ls-files -u outputs: mode sha stage\tpath — deduplicate paths
            seen: set[str] = set()
            for line in result.stdout.strip().splitlines():
                parts = line.split("\t", 1)
                if len(parts) == 2 and parts[1].strip() not in seen:
                    seen.add(parts[1].strip())
                    conflict_files.append(parts[1].strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    return RepoContextResponse(
        branch=branch,
        recent_commits=recent_commits,
        claude_md=claude_md,
        file_tree=file_tree,
        conflict_files=conflict_files,
        branch_switched_from=branch_switched_from,
    )


class WorktreeResponse(BaseModel):
    path: str
    branch: str
    head_sha: str
    is_primary: bool


@web_router.get("/repos/{name}/worktrees", response_model=list[WorktreeResponse])
def list_worktrees(name: str) -> list[WorktreeResponse]:
    """List active git worktrees for a repo."""
    from deathstar_server.app_state import worktree_manager
    repo_root = git_service.resolve_target(name)
    worktrees = worktree_manager.list_worktrees(repo_root)
    return [
        WorktreeResponse(
            path=str(wt.path),
            branch=wt.branch,
            head_sha=wt.head_sha,
            is_primary=wt.is_primary,
        )
        for wt in worktrees
    ]


@web_router.get("/repos/{name}/branches")
def list_branches(name: str) -> dict[str, object]:
    """List local branches and identify the current one."""
    repo_root = git_service.resolve_target(name)
    try:
        result = subprocess.run(
            ["git", "branch", "--format=%(refname:short)"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
        branches = [b.strip() for b in result.stdout.strip().splitlines() if b.strip()]
    except subprocess.CalledProcessError:
        branches = []

    try:
        current = git_service.current_branch(repo_root)
    except AppError:
        current = "unknown"

    return {"branches": branches, "current": current}


@web_router.get("/repos/{name}/commits")
def list_commits(
    name: str,
    limit: int = Query(default=30, ge=1, le=100),
) -> list[dict]:
    """Return recent commits for the current branch."""
    repo_root = git_service.resolve_target(name)
    try:
        result = subprocess.run(
            [
                "git", "log",
                f"-{limit}",
                "--format=%H%n%h%n%s%n%an%n%aI",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return []

    lines = result.stdout.strip().splitlines()
    commits = []
    # Each commit is 5 lines: full sha, short sha, message, author, ISO date
    for i in range(0, len(lines) - 4, 5):
        commits.append({
            "sha": lines[i],
            "short_sha": lines[i + 1],
            "message": lines[i + 2],
            "author": lines[i + 3],
            "date": lines[i + 4],
        })
    return commits


@web_router.post("/repos/{name}/branch")
def create_branch(name: str, request: BranchRequest) -> dict[str, str]:
    """Create a new branch in the repo. Rejects 'main'/'master'."""
    if request.branch.startswith("-"):
        raise AppError(ErrorCode.INVALID_REQUEST, "branch name must not start with '-'", status_code=400)
    if request.from_branch and request.from_branch.startswith("-"):
        raise AppError(ErrorCode.INVALID_REQUEST, "from_branch must not start with '-'", status_code=400)
    repo_root = git_service.resolve_target(name)
    try:
        cmd = ["git", "checkout", "-b", request.branch]
        if request.from_branch:
            cmd.append(request.from_branch)
        subprocess.run(
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            f"failed to create branch: {(exc.stderr or '').strip()[:200]}",
            status_code=500,
        ) from exc
    # Publish branch_update event
    event_bus.publish(RepoEvent(
        event_type=EVENT_BRANCH_UPDATE,
        repo=name,
        source=SOURCE_LOCAL,
        data={"action": "created", "branch": request.branch},
    ))

    return {"branch": request.branch}


@web_router.post("/repos/{name}/checkout")
def checkout_branch(name: str, request: CheckoutRequest) -> dict:
    """Switch to an existing branch. Auto-commits uncommitted changes first."""
    if request.branch.startswith("-"):
        raise AppError(ErrorCode.INVALID_REQUEST, "branch name must not start with '-'", status_code=400)
    repo_root = git_service.resolve_target(name)

    # Agent sessions run in isolated worktrees, so switching the primary
    # checkout is safe and should never be blocked by an active agent.

    auto_committed = False
    auto_commit_branch: str | None = None

    # Auto-commit dirty changes before switching
    if git_service.has_uncommitted_changes(repo_root):
        try:
            auto_commit_branch = git_service.current_branch(repo_root)
        except Exception:
            auto_commit_branch = "unknown"
        try:
            git_service.commit_all(
                repo_root,
                f"WIP: auto-commit before switching to {request.branch}",
            )
            auto_committed = True
        except Exception as exc:
            logger.warning("auto-commit failed before branch switch: %s", exc)

    try:
        subprocess.run(
            ["git", "checkout", request.branch],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            f"failed to checkout branch: {(exc.stderr or '').strip()[:200]}",
            status_code=500,
        ) from exc

    # Publish local_checkout event
    event_bus.publish(RepoEvent(
        event_type=EVENT_LOCAL_CHECKOUT,
        repo=name,
        source=SOURCE_LOCAL,
        data={"from_branch": auto_commit_branch or "unknown", "to_branch": request.branch},
    ))

    result: dict = {"branch": request.branch}
    if auto_committed:
        result["auto_committed"] = True
        result["auto_commit_branch"] = auto_commit_branch
    return result


@web_router.delete("/repos/{name}/branch")
def delete_branch(name: str, request: BranchRequest) -> dict[str, str]:
    """Delete a local branch. Refuses to delete current, main, or master."""
    if request.branch.startswith("-"):
        raise AppError(ErrorCode.INVALID_REQUEST, "branch name must not start with '-'", status_code=400)
    if request.branch in ("main", "master"):
        raise AppError(ErrorCode.INVALID_REQUEST, "cannot delete default branch", status_code=400)
    repo_root = git_service.resolve_target(name)

    # Prevent deleting the currently checked-out branch
    try:
        current = git_service.current_branch(repo_root)
    except Exception:
        current = None
    if current and current == request.branch:
        raise AppError(ErrorCode.INVALID_REQUEST, "cannot delete the currently checked-out branch", status_code=400)

    try:
        subprocess.run(
            ["git", "branch", "-D", request.branch],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            f"failed to delete branch: {(exc.stderr or '').strip()[:200]}",
            status_code=500,
        ) from exc
    # Publish branch_update event
    event_bus.publish(RepoEvent(
        event_type=EVENT_BRANCH_UPDATE,
        repo=name,
        source=SOURCE_LOCAL,
        data={"action": "deleted", "branch": request.branch},
    ))

    return {"branch": request.branch}


class SyncBranchRequest(BaseModel):
    base_branch: str = "main"


@web_router.post("/repos/{name}/sync")
def sync_branch(name: str, body: SyncBranchRequest) -> dict:
    """Fetch latest from origin, rebase current branch onto base_branch.

    Workflow: fetch → stash dirty changes → checkout base → pull → checkout back → rebase → pop stash.
    Returns conflict info if rebase fails.
    """
    if body.base_branch.startswith("-"):
        raise AppError(ErrorCode.INVALID_REQUEST, "base_branch must not start with '-'", status_code=400)
    repo_root = git_service.resolve_target(name)
    current = git_service.current_branch(repo_root)

    # Agent sessions run in isolated worktrees, so syncing the primary
    # checkout is safe and should never be blocked by an active agent.

    def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=check,
        )

    # Fetch latest
    _git("fetch", "origin", check=False)

    # Capture HEAD before rebase to detect no-op syncs
    head_before = _git("rev-parse", "HEAD", check=False).stdout.strip()

    # Stash any dirty changes
    had_stash = False
    if git_service.has_uncommitted_changes(repo_root):
        _git("stash", "push", "-m", "deathstar-sync-stash")
        had_stash = True

    conflict = False
    conflict_files: list[str] = []
    message = ""

    try:
        if current == body.base_branch:
            # Already on base branch — just pull
            result = _git("rebase", f"origin/{body.base_branch}", check=False)
            if result.returncode != 0:
                conflict = True
                message = (result.stderr or result.stdout).strip()[:300]
                _git("rebase", "--abort", check=False)
            else:
                message = f"Updated {body.base_branch} from origin"
        else:
            # Find the fork point — only replay commits unique to this branch.
            # This avoids duplicating commits that were already squash-merged into main.
            merge_base = _git("merge-base", "HEAD", f"origin/{body.base_branch}", check=False)
            if merge_base.returncode == 0 and merge_base.stdout.strip():
                fork_point = merge_base.stdout.strip()
                result = _git(
                    "rebase", "--onto", f"origin/{body.base_branch}", fork_point, check=False,
                )
            else:
                # Fallback if merge-base fails
                result = _git("rebase", f"origin/{body.base_branch}", check=False)

            if result.returncode != 0:
                conflict = True
                message = (result.stderr or result.stdout).strip()[:300]
                # Collect conflict files before aborting
                ls_result = _git("ls-files", "-u", check=False)
                if ls_result.stdout.strip():
                    seen: set[str] = set()
                    for line in ls_result.stdout.strip().splitlines():
                        parts = line.split("\t", 1)
                        if len(parts) == 2 and parts[1].strip() not in seen:
                            seen.add(parts[1].strip())
                            conflict_files.append(parts[1].strip())
                _git("rebase", "--abort", check=False)
            else:
                message = f"Rebased {current} onto origin/{body.base_branch}"
    finally:
        # Restore stashed changes
        if had_stash:
            _git("stash", "pop", check=False)

    # Check if HEAD actually moved
    head_after = _git("rev-parse", "HEAD", check=False).stdout.strip()
    up_to_date = not conflict and head_before == head_after

    return {
        "branch": current,
        "base_branch": body.base_branch,
        "conflict": conflict,
        "conflict_files": conflict_files,
        "message": message if not up_to_date else f"Already up to date with origin/{body.base_branch}",
        "up_to_date": up_to_date,
    }


class QuickSaveRequest(BaseModel):
    context: str | None = None  # Last assistant message for smarter commit messages


@web_router.post("/repos/{name}/save")
def quick_save(name: str, body: QuickSaveRequest | None = None) -> dict:
    """Auto-commit all changes with a generated commit message.

    If ``context`` is provided (e.g. the last assistant message describing
    what was changed), it is used to produce a meaningful commit message.
    Otherwise falls back to a mechanical summary from ``git status``.
    """
    repo_root = git_service.resolve_target(name)

    if not git_service.has_uncommitted_changes(repo_root):
        return {"saved": False, "message": "Nothing to commit"}

    context = body.context if body else None

    if context:
        # Extract a short commit message from the agent context.
        # Take the first sentence/line, cap at 72 chars for git convention.
        first_line = context.strip().split("\n")[0].strip()
        # Strip leading markdown like "I've ", "Done — ", etc.
        for prefix in ("I've ", "I have ", "Done — ", "Done. ", "OK — ", "OK. "):
            if first_line.lower().startswith(prefix.lower()):
                first_line = first_line[len(prefix):]
                break
        # Capitalize and truncate
        if first_line:
            message = first_line[0].upper() + first_line[1:]
            if len(message) > 72:
                message = message[:69] + "..."
        else:
            message = _build_status_message(repo_root)
    else:
        message = _build_status_message(repo_root)

    try:
        sha = git_service.commit_all(repo_root, message)
    except Exception as exc:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            f"failed to commit: {str(exc)[:200]}",
            status_code=500,
        ) from exc

    # Publish local_commit event
    try:
        branch = git_service.current_branch(repo_root)
    except subprocess.CalledProcessError:
        branch = "unknown"
    event_bus.publish(RepoEvent(
        event_type=EVENT_LOCAL_COMMIT,
        repo=name,
        source=SOURCE_LOCAL,
        data={"sha": sha or "", "message": message, "branch": branch},
    ))

    return {"saved": True, "message": message, "sha": sha}


def _build_status_message(repo_root: Path) -> str:
    """Build a commit message from git status output."""
    status_output = subprocess.run(
        ["git", "status", "--short"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    ).stdout.strip()

    lines = [ln.strip() for ln in status_output.splitlines() if ln.strip()]
    modified, added, deleted, renamed = [], [], [], []
    for line in lines:
        code = line[:2].strip()
        path = line[2:].strip().split(" -> ")[-1]
        filename = path.rsplit("/", 1)[-1]
        if code.startswith("R"):
            renamed.append(filename)
        elif code in ("D",):
            deleted.append(filename)
        elif code in ("??", "A"):
            added.append(filename)
        else:
            modified.append(filename)

    parts = []
    if modified:
        if len(modified) <= 3:
            parts.append(f"update {', '.join(modified)}")
        else:
            parts.append(f"update {len(modified)} files")
    if added:
        if len(added) <= 3:
            parts.append(f"add {', '.join(added)}")
        else:
            parts.append(f"add {len(added)} files")
    if deleted:
        if len(deleted) <= 3:
            parts.append(f"remove {', '.join(deleted)}")
        else:
            parts.append(f"remove {len(deleted)} files")
    if renamed:
        if len(renamed) <= 3:
            parts.append(f"rename {', '.join(renamed)}")
        else:
            parts.append(f"rename {len(renamed)} files")

    message = "; ".join(parts) if parts else "save changes"
    return message[0].upper() + message[1:]


# ---------------------------------------------------------------------------
# Claude CLI Auth
# ---------------------------------------------------------------------------

_TOKEN_FILE = "oauth_token"
_ONBOARDING_FILE = ".claude.json"


def _claude_config_dir() -> Path:
    """Return the persistent Claude config directory on the workspace volume."""
    return settings.workspace_root / "deathstar" / ".claude"




def _claude_env() -> dict[str, str]:
    """Build env dict for Claude CLI commands with persistent config dir."""
    env = os.environ.copy()
    claude_home = str(_claude_config_dir())
    env["CLAUDE_CONFIG_DIR"] = claude_home
    env.setdefault("HOME", "/root")
    token = _load_stored_token()
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    return env


def _store_token(token: str) -> None:
    """Persist an OAuth token to the workspace config dir."""
    config_dir = _claude_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    # Restrict directory permissions
    config_dir.chmod(0o700)
    token_path = config_dir / _TOKEN_FILE
    token_path.write_text(token)
    token_path.chmod(0o600)
    # Ensure onboarding flag exists so CLI doesn't prompt
    onboarding_path = config_dir / _ONBOARDING_FILE
    if not onboarding_path.exists():
        onboarding_path.write_text('{"hasCompletedOnboarding": true}\n')


def _load_stored_token() -> str | None:
    """Load stored OAuth token, or None."""
    token_path = _claude_config_dir() / _TOKEN_FILE
    if token_path.is_file():
        token = token_path.read_text().strip()
        return token or None
    return None


def _clear_stored_token() -> None:
    """Remove stored OAuth token."""
    token_path = _claude_config_dir() / _TOKEN_FILE
    if token_path.is_file():
        token_path.unlink()


@web_router.get("/claude/auth/status")
def claude_auth_status() -> dict:
    """Check if a Claude token is stored."""
    has_token = _load_stored_token() is not None
    return {"authenticated": has_token}


@web_router.post("/claude/auth/token")
def claude_auth_token(body: dict) -> dict:
    """Store an OAuth token from `claude setup-token`."""
    token = body.get("token", "").strip()
    if not token:
        return {"success": False, "error": "No token provided"}

    _store_token(token)
    return {"success": True, "message": "Token saved"}


@web_router.post("/claude/auth/logout")
def claude_auth_logout() -> dict:
    """Clear stored token and log out of Claude CLI."""
    _clear_stored_token()
    try:
        subprocess.run(
            ["claude", "auth", "logout"],
            capture_output=True,
            text=True,
            timeout=10,
            env=_claude_env(),
        )
        return {"success": True, "message": "Disconnected"}
    except Exception:
        return {"success": True, "message": "Token cleared"}


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------


@web_router.get("/github/repos", response_model=list[GitHubRepoInfo])
def list_github_repos() -> list[GitHubRepoInfo]:
    """List repos accessible to the configured GITHUB_TOKEN."""
    if not settings.github_token:
        raise AppError(
            ErrorCode.INTEGRATION_NOT_CONFIGURED,
            "GITHUB_TOKEN is not set",
            status_code=400,
        )

    import httpx

    repos: list[GitHubRepoInfo] = []
    page = 1
    while page <= 5:  # Cap at 5 pages (500 repos)
        resp = httpx.get(
            "https://api.github.com/user/repos",
            params={"per_page": 100, "page": page, "sort": "updated", "direction": "desc"},
            headers={
                "Authorization": f"Bearer {settings.github_token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=15,
        )
        if resp.status_code != 200:
            if page == 1:
                raise AppError(
                    ErrorCode.AUTH_ERROR,
                    f"GitHub API error: {resp.status_code}",
                    status_code=502,
                )
            break

        data = resp.json()
        if not data:
            break

        for item in data:
            repos.append(GitHubRepoInfo(
                full_name=item["full_name"],
                name=item["name"],
                description=item.get("description"),
                default_branch=item.get("default_branch", "main"),
                private=item.get("private", False),
                updated_at=item.get("updated_at", ""),
                language=item.get("language"),
            ))
        page += 1

    return repos


@web_router.post("/github/clone")
def clone_github_repo(request: CloneRequest) -> dict[str, str | None]:
    """Clone a GitHub repo into the projects directory."""
    if not settings.github_token:
        raise AppError(
            ErrorCode.INTEGRATION_NOT_CONFIGURED,
            "GITHUB_TOKEN is not set",
            status_code=400,
        )

    projects = settings.projects_root
    projects.mkdir(parents=True, exist_ok=True)

    repo_name = request.full_name.split("/")[-1]
    target = projects / repo_name
    if target.exists():
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            f"repo '{repo_name}' already exists locally",
            status_code=409,
        )

    import shutil

    try:
        if shutil.which("gh"):
            import os
            subprocess.run(
                ["gh", "repo", "clone", request.full_name, repo_name],
                cwd=str(projects),
                capture_output=True,
                text=True,
                check=True,
                env={**os.environ, "GITHUB_TOKEN": settings.github_token},
            )
        else:
            # Fallback: git clone with HTTPS token auth
            clone_url = f"https://x-access-token:{settings.github_token}@github.com/{request.full_name}.git"
            subprocess.run(
                ["git", "clone", clone_url, repo_name],
                cwd=str(projects),
                capture_output=True,
                text=True,
                check=True,
            )
            # Remove token from persisted remote URL in .git/config
            clean_url = f"https://github.com/{request.full_name}.git"
            subprocess.run(
                ["git", "remote", "set-url", "origin", clean_url],
                cwd=str(target),
                capture_output=True,
                text=True,
                check=False,
            )
    except subprocess.CalledProcessError as exc:
        # Sanitize stderr to avoid leaking tokens from git clone URLs
        stderr = (exc.stderr or "").strip()[:200]
        if settings.github_token and settings.github_token in stderr:
            stderr = stderr.replace(settings.github_token, "***")
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            f"clone failed: {stderr}",
            status_code=500,
        ) from exc

    # Install dependencies so git hooks (husky, etc.) work on commits
    pkg_manager = git_service.install_deps(target)

    return {"name": repo_name, "deps_installed": pkg_manager}


@web_router.post("/repos/{name}/install")
def install_deps(name: str) -> dict:
    """Install project dependencies (npm/yarn/pnpm/pip/uv) for a repo.

    This ensures git hooks like husky work correctly on commits.
    """
    repo_root = git_service.resolve_target(name)
    pkg_manager = git_service.install_deps(repo_root)
    if pkg_manager:
        return {"installed": True, "package_manager": pkg_manager}
    return {"installed": False, "message": "No recognized package manager found"}


@web_router.get("/repos/{name}/pulls", response_model=list[GitHubPullRequestSummary])
async def list_pull_requests(
    name: str,
    state: str = Query(default="open", pattern="^(open|closed|all)$"),
) -> list[dict]:
    """List pull requests for a repo from GitHub."""
    from deathstar_server.app_state import github_service
    repo_root = git_service.resolve_target(name)
    return await github_service.list_pull_requests(repo_root=repo_root, state=state)


# ---------------------------------------------------------------------------
# Reviews (GitHub integration)
# ---------------------------------------------------------------------------


@web_router.post("/reviews/post-to-github")
async def post_review_to_github(request: PostReviewRequest) -> dict:
    """Post a structured review to GitHub as a PR review with inline comments."""
    from deathstar_server.app_state import github_service
    from deathstar_server.services.github import GitHubService

    owner, repo_name, pr_number = GitHubService.parse_pr_url(request.pr_url)
    result = await github_service.submit_review(
        owner=owner,
        repo=repo_name,
        pr_number=pr_number,
        summary=request.summary,
        verdict=request.verdict,
        findings=request.findings,
    )
    return {
        "review_id": result.get("id"),
        "html_url": result.get("html_url", ""),
        "state": result.get("state", ""),
    }


@web_router.post("/reviews/apply-suggestions", response_model=ApplySuggestionsResponse)
async def apply_suggestions(request: ApplySuggestionsRequest) -> ApplySuggestionsResponse:
    """Commit accepted code suggestions to the PR branch via GitHub Git Data API."""
    from deathstar_server.app_state import github_service
    from deathstar_server.services.github import GitHubService

    owner, repo_name, pr_number = GitHubService.parse_pr_url(request.pr_url)
    result = await github_service.apply_file_changes(
        owner=owner,
        repo=repo_name,
        pr_number=pr_number,
        findings=request.findings,
        commit_message=request.commit_message,
    )
    return ApplySuggestionsResponse(**result)


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------


@web_router.get("/conversations", response_model=list[ConversationSummary])
def list_conversations(
    repo: str | None = Query(default=None),
    branch: str | None = Query(default=None),
) -> list[ConversationSummary]:
    return _get_conversation_store().list_conversations(repo, branch)


@web_router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: str) -> ConversationDetail:
    detail = _get_conversation_store().get_conversation(conversation_id)
    if detail is None:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "conversation not found",
            status_code=404,
        )
    return detail


@web_router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str) -> dict[str, bool]:
    deleted = _get_conversation_store().delete_conversation(conversation_id)
    if not deleted:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "conversation not found",
            status_code=404,
        )
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Memory Bank
# ---------------------------------------------------------------------------


@web_router.get("/memory", response_model=list[MemoryEntryResponse])
def list_memories(repo: str | None = Query(default=None)) -> list[dict[str, object]]:
    return _get_memory_bank().list_memories(repo)


@web_router.post("/memory", response_model=MemoryEntryResponse)
def save_memory(request: SaveMemoryRequest) -> dict[str, object]:
    return _get_memory_bank().save_memory(
        repo=request.repo,
        content=request.content,
        source_message_id=request.source_message_id,
        source_prompt=request.source_prompt,
        tags=request.tags,
    )


@web_router.delete("/memory/{memory_id}")
def delete_memory(memory_id: str) -> dict[str, bool]:
    deleted = _get_memory_bank().delete_memory(memory_id)
    if not deleted:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "memory not found",
            status_code=404,
        )
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------


@web_router.post("/feedback", response_model=FeedbackResponse)
def save_feedback(request: FeedbackRequest) -> dict[str, object]:
    return _get_feedback_store().save_feedback(
        message_id=request.message_id,
        conversation_id=request.conversation_id,
        kind=request.kind.value,
        repo=request.repo,
        content=request.content,
        prompt=request.prompt,
        comment=request.comment,
    )


@web_router.get("/feedback")
def list_feedback(
    repo: str | None = Query(default=None),
    kind: str | None = Query(default=None, pattern="^(thumbs_up|thumbs_down)$"),
) -> list[dict[str, object]]:
    return _get_feedback_store().list_feedback(repo=repo, kind=kind)


# ---------------------------------------------------------------------------
# Message Queue
# ---------------------------------------------------------------------------


@web_router.post("/queue")
def enqueue_message(request: EnqueueRequest) -> QueueItemResponse:
    """Add a message to the async processing queue."""
    from deathstar_server.app_state import conversation_store, queue_store, queue_worker

    # Validate repo exists
    try:
        git_service.resolve_target(request.repo)
    except AppError:
        raise AppError(ErrorCode.INVALID_REQUEST, f"repo '{request.repo}' not found", status_code=404)

    conversation_id = conversation_store.get_or_create(
        request.conversation_id, request.repo, request.branch,
    )
    item = queue_store.enqueue(
        conversation_id=conversation_id,
        repo=request.repo,
        branch=request.branch,
        message=request.message,
        workflow=request.workflow,
        model=request.model,
        system_prompt=request.system_prompt,
    )
    queue_worker.notify()
    return QueueItemResponse(**{k: item[k] for k in QueueItemResponse.model_fields})


@web_router.get("/queue")
def list_queue(
    conversation_id: str | None = Query(default=None),
    repo: str | None = Query(default=None),
) -> list[QueueItemResponse]:
    """List pending and processing queue items."""
    from deathstar_server.app_state import queue_store

    items = queue_store.list_pending(conversation_id=conversation_id, repo=repo)
    return [
        QueueItemResponse(**{k: item[k] for k in QueueItemResponse.model_fields})
        for item in items
    ]


@web_router.delete("/queue/{item_id}")
def cancel_queue_item(item_id: str) -> dict[str, bool]:
    """Cancel a pending queue item."""
    from deathstar_server.app_state import queue_store

    cancelled = queue_store.cancel(item_id)
    if not cancelled:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "queue item not found or already processed",
            status_code=404,
        )
    return {"cancelled": True}
