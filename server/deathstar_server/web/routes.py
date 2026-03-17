from __future__ import annotations

import logging
import subprocess

from fastapi import APIRouter, Query

from deathstar_server.app_state import git_service, settings, workflow_service
from deathstar_server.errors import AppError
from deathstar_shared.models import (
    BranchRequest,
    ChatRequest,
    ChatResponse,
    CloneRequest,
    ConversationDetail,
    ConversationSummary,
    ErrorCode,
    GitHubRepoInfo,
    MemoryEntryResponse,
    ProviderName,
    ProviderStatus,
    RepoContextResponse,
    RepoInfo,
    SaveMemoryRequest,
    WorkflowRequest,
)

logger = logging.getLogger(__name__)

web_router = APIRouter(prefix="/web/api")


def _get_conversation_store():
    from deathstar_server.app_state import conversation_store
    return conversation_store


def _get_memory_bank():
    from deathstar_server.app_state import memory_bank
    return memory_bank


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


@web_router.get("/repos/{name}/context", response_model=RepoContextResponse)
def repo_context(name: str) -> RepoContextResponse:
    """Return repo context for LLM enrichment: branch, commits, CLAUDE.md, file tree."""
    repo_root = git_service.resolve_target(name)

    # Branch
    try:
        branch = git_service.current_branch(repo_root)
    except AppError:
        branch = "unknown"

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

    return RepoContextResponse(
        branch=branch,
        recent_commits=recent_commits,
        claude_md=claude_md,
        file_tree=file_tree,
    )


@web_router.post("/repos/{name}/branch")
def create_branch(name: str, request: BranchRequest) -> dict[str, str]:
    """Create a new branch in the repo. Rejects 'main'/'master'."""
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
    return {"branch": request.branch}


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
def clone_github_repo(request: CloneRequest) -> dict[str, str]:
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

    try:
        subprocess.run(
            ["gh", "repo", "clone", request.full_name],
            cwd=str(projects),
            capture_output=True,
            text=True,
            check=True,
            env={
                **__import__("os").environ,
                "GITHUB_TOKEN": settings.github_token,
            },
        )
    except subprocess.CalledProcessError as exc:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            f"clone failed: {(exc.stderr or '').strip()[:200]}",
            status_code=500,
        ) from exc

    return {"name": repo_name}


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


@web_router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    store = _get_conversation_store()

    # Resolve provider — pick first configured if not specified
    provider = request.provider
    if provider is None:
        status = workflow_service.providers.status()
        for name, info in status.items():
            if info.configured:
                provider = ProviderName(name)
                break
        if provider is None:
            raise AppError(
                ErrorCode.PROVIDER_NOT_CONFIGURED,
                "no providers are configured",
                status_code=400,
            )

    conversation_id = store.get_or_create(request.conversation_id, request.repo)
    store.add_user_message(conversation_id, request.message)

    # Build prompt with conversation history
    history = store.build_history_prompt(conversation_id)
    prompt = request.message
    if history:
        prompt = f"{history}\n\nCurrent message:\n{request.message}"

    workflow_request = WorkflowRequest(
        workflow=request.workflow,
        provider=provider,
        prompt=prompt,
        workspace_subpath=request.repo,
        model=request.model,
        system=request.system,
        write_changes=request.write_changes,
    )

    result = await workflow_service.execute(workflow_request)

    content = result.content or ""
    if result.error:
        content = result.error.message

    msg_id = store.add_assistant_message(
        conversation_id,
        content,
        workflow=result.workflow,
        provider=result.provider,
        model=result.model,
        duration_ms=result.duration_ms,
    )

    return ChatResponse(
        conversation_id=conversation_id,
        message_id=msg_id,
        content=result.content,
        workflow=result.workflow,
        provider=result.provider,
        model=result.model,
        duration_ms=result.duration_ms,
        usage=result.usage,
        error=result.error,
        status=result.status,
    )


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------


@web_router.get("/conversations", response_model=list[ConversationSummary])
def list_conversations(repo: str | None = Query(default=None)) -> list[ConversationSummary]:
    return _get_conversation_store().list_conversations(repo)


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
# Providers
# ---------------------------------------------------------------------------


@web_router.get("/providers", response_model=dict[str, ProviderStatus])
def list_providers() -> dict[str, ProviderStatus]:
    return workflow_service.providers.status()


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
