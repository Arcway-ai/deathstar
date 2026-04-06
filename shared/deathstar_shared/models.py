from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DeathStarModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, use_enum_values=True)


class ProviderName(str, Enum):
    ANTHROPIC = "anthropic"


class WorkflowKind(str, Enum):
    PROMPT = "prompt"
    PATCH = "patch"
    PR = "pr"
    REVIEW = "review"
    DOCS = "docs"
    AUDIT = "audit"
    PLAN = "plan"


class ErrorCode(str, Enum):
    AUTH_ERROR = "auth_error"
    INVALID_REQUEST = "invalid_request"
    INVALID_PROVIDER_OUTPUT = "invalid_provider_output"
    INTEGRATION_NOT_CONFIGURED = "integration_not_configured"
    INTERNAL_ERROR = "internal_error"
    PROVIDER_NOT_CONFIGURED = "provider_not_configured"
    RATE_LIMITED = "rate_limited"
    UPSTREAM_TIMEOUT = "upstream_timeout"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    BACKUP_NOT_FOUND = "backup_not_found"


class UsageMetrics(DeathStarModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class ErrorEnvelope(DeathStarModel):
    code: ErrorCode
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class WorkflowRequest(DeathStarModel):
    workflow: WorkflowKind = WorkflowKind.PROMPT
    provider: ProviderName
    prompt: str = Field(min_length=1, max_length=200_000)
    workspace_subpath: str = Field(default=".", pattern=r"^[a-zA-Z0-9_./ -]+$|^\.$")

    @field_validator("workspace_subpath")
    @classmethod
    def _reject_path_traversal(cls, value: str) -> str:
        if value == "..":
            raise ValueError("workspace_subpath must not be '..'")
        if value.startswith("../"):
            raise ValueError("workspace_subpath must not start with '../'")
        if "/../" in value or value.endswith("/.."):
            raise ValueError("workspace_subpath must not contain path traversal")
        if value.startswith("/"):
            raise ValueError("workspace_subpath must not be an absolute path")
        return value
    model: str | None = Field(default=None, max_length=200)
    system: str | None = Field(default=None, max_length=200_000)
    timeout_seconds: int = Field(default=180, ge=5, le=900)
    write_changes: bool = False
    base_branch: str = Field(default="main", pattern=r"^[a-zA-Z0-9_./-]+$", max_length=200)
    head_branch: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_./-]+$", max_length=200)
    open_pr: bool = False
    draft_pr: bool = False


class WorkflowResponse(DeathStarModel):
    request_id: str
    workflow: WorkflowKind
    status: Literal["succeeded", "failed"]
    provider: ProviderName
    model: str
    content: str | None = None
    workspace_subpath: str
    duration_ms: int
    usage: UsageMetrics | None = None
    error: ErrorEnvelope | None = None
    artifacts: dict[str, Any] = Field(default_factory=dict)


class ProviderStatus(DeathStarModel):
    configured: bool
    default_model: str


class StatusResponse(DeathStarModel):
    service: Literal["healthy"]
    version: str
    workspace_root: str
    projects_root: str
    log_path: str
    backup_directory: str
    backup_bucket: str | None = None
    github_prs_enabled: bool = False
    preferred_transport: Literal["tailscale", "ssm"] = "ssm"
    tailscale_enabled: bool = False
    tailscale_hostname: str | None = None
    ssh_user: str = "ubuntu"
    providers: dict[str, ProviderStatus]
    workflows: list[WorkflowKind]


class LogsResponse(DeathStarModel):
    lines: list[str]


class BackupRequest(DeathStarModel):
    label: str | None = Field(default=None, max_length=200)


class BackupResponse(DeathStarModel):
    backup_id: str
    created_at: datetime
    local_path: str
    s3_uri: str | None = None


class RestoreRequest(DeathStarModel):
    backup_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9._-]+\.tar\.gz$")


class RestoreResponse(DeathStarModel):
    backup_id: str
    restored_from: str
    projects_root: str


# ---------------------------------------------------------------------------
# Web UI models
# ---------------------------------------------------------------------------


class ReviewSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    SUGGESTION = "suggestion"
    NITPICK = "nitpick"


class ReviewVerdict(str, Enum):
    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"
    COMMENT = "comment"


class ReviewFinding(DeathStarModel):
    id: str
    file: str
    line_start: int | None = None
    line_end: int | None = None
    severity: ReviewSeverity
    title: str
    body: str
    original_code: str | None = None
    suggested_code: str | None = None


class StructuredReview(DeathStarModel):
    summary: str
    verdict: ReviewVerdict
    findings: list[ReviewFinding] = Field(default_factory=list)


class PostReviewRequest(DeathStarModel):
    pr_url: str = Field(max_length=500)
    summary: str = Field(max_length=10_000)
    verdict: ReviewVerdict
    findings: list[ReviewFinding] = Field(default_factory=list)


class ApplySuggestionsRequest(DeathStarModel):
    pr_url: str = Field(max_length=500)
    findings: list[ReviewFinding]
    commit_message: str | None = Field(default=None, max_length=500)


class ApplySuggestionsResponse(DeathStarModel):
    commit_sha: str
    files_changed: int
    commit_url: str
    applied: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)


class RepoInfo(DeathStarModel):
    name: str
    branch: str
    dirty: bool


class GitHubPullRequestSummary(DeathStarModel):
    number: int
    title: str
    state: str
    user: str
    head_branch: str
    base_branch: str
    updated_at: str
    additions: int | None = None
    deletions: int | None = None
    changed_files: int | None = None
    draft: bool = False
    url: str


class ChatRequest(DeathStarModel):
    repo: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_./ -]+$")
    message: str = Field(min_length=1, max_length=200_000)
    conversation_id: str | None = None
    workflow: WorkflowKind = WorkflowKind.PROMPT
    provider: ProviderName | None = None
    model: str | None = Field(default=None, max_length=200)
    system: str | None = Field(default=None, max_length=200_000)
    write_changes: bool = False
    pr_url: str | None = Field(default=None, max_length=500)

    @field_validator("repo")
    @classmethod
    def _reject_repo_traversal(cls, value: str) -> str:
        if value == ".." or value.startswith("../") or "/../" in value or value.endswith("/.."):
            raise ValueError("repo must not contain path traversal")
        if value.startswith("/"):
            raise ValueError("repo must not be an absolute path")
        return value


class ChatResponse(DeathStarModel):
    conversation_id: str
    message_id: str
    content: str | None = None
    workflow: WorkflowKind
    provider: ProviderName
    model: str
    duration_ms: int
    usage: UsageMetrics | None = None
    cost_usd: float | None = None
    error: ErrorEnvelope | None = None
    status: Literal["succeeded", "failed"]


class ConversationMessage(DeathStarModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    timestamp: datetime
    workflow: WorkflowKind | None = None
    provider: ProviderName | None = None
    model: str | None = None
    duration_ms: int | None = None
    agent_blocks: list[dict[str, Any]] | None = None


class ConversationSummary(DeathStarModel):
    id: str
    repo: str
    title: str
    message_count: int
    created_at: datetime
    updated_at: datetime
    branch: str | None = None
    branches: list[str] = Field(default_factory=list)


class ConversationDetail(DeathStarModel):
    id: str
    repo: str
    title: str
    messages: list[ConversationMessage]
    created_at: datetime
    updated_at: datetime
    branch: str | None = None
    branches: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------


class GitHubRepoInfo(DeathStarModel):
    full_name: str
    name: str
    description: str | None = None
    default_branch: str = "main"
    private: bool = False
    updated_at: str = ""
    language: str | None = None


class CloneRequest(DeathStarModel):
    full_name: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+$")


class CheckoutRequest(DeathStarModel):
    """Checkout an existing branch (allows main/master)."""
    branch: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_./-]+$", max_length=200)


class BranchRequest(DeathStarModel):
    """Create or delete a branch (rejects main/master)."""
    branch: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_./-]+$", max_length=200)
    from_branch: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_./-]+$", max_length=200)

    @field_validator("branch")
    @classmethod
    def _reject_main(cls, value: str) -> str:
        if value in ("main", "master"):
            raise ValueError("cannot create a branch named 'main' or 'master'")
        return value


# ---------------------------------------------------------------------------
# Memory Bank
# ---------------------------------------------------------------------------


class MemoryEntryResponse(DeathStarModel):
    id: str
    repo: str
    content: str
    source_message_id: str
    source_prompt: str
    tags: list[str]
    created_at: datetime


class SaveMemoryRequest(DeathStarModel):
    repo: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_./ -]+$")
    content: str = Field(min_length=1, max_length=10_000)
    source_message_id: str = Field(default="", max_length=200)
    source_prompt: str = Field(default="", max_length=2000)
    tags: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


class DocumentResponse(DeathStarModel):
    id: str
    repo: str
    title: str
    content: str
    document_type: str
    source_conversation_id: str | None
    created_at: datetime
    updated_at: datetime


class CreateDocumentRequest(DeathStarModel):
    repo: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_./ -]+$")
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=200_000)
    document_type: Literal["tech_spec", "design_doc", "bug_analysis", "plan", "notes"] = "tech_spec"
    source_conversation_id: str | None = Field(default=None, max_length=200)


class UpdateDocumentRequest(DeathStarModel):
    title: str | None = Field(default=None, max_length=500)
    content: str | None = Field(default=None, max_length=200_000)
    document_type: Literal["tech_spec", "design_doc", "bug_analysis", "plan", "notes"] | None = None


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------


class FeedbackKind(str, Enum):
    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"


class FeedbackRequest(DeathStarModel):
    message_id: str = Field(min_length=1, max_length=200)
    conversation_id: str | None = Field(default=None, max_length=200)
    kind: FeedbackKind
    repo: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_./ -]+$")
    content: str = Field(default="", max_length=10_000)
    prompt: str = Field(default="", max_length=2000)
    comment: str = Field(default="", max_length=1000)


class FeedbackResponse(DeathStarModel):
    id: str
    message_id: str
    kind: FeedbackKind
    repo: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Message Queue
# ---------------------------------------------------------------------------


QueueStatus = Literal["pending", "processing", "completed", "failed", "cancelled"]


class EnqueueRequest(DeathStarModel):
    conversation_id: str | None = Field(default=None, max_length=200)
    repo: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_./ -]+$")
    branch: str | None = Field(default=None, max_length=256, pattern=r"^[a-zA-Z0-9_./-]+$")
    message: str = Field(min_length=1, max_length=100_000)
    workflow: WorkflowKind = WorkflowKind.PROMPT
    model: str | None = Field(default=None, max_length=200)
    system_prompt: str | None = Field(default=None, max_length=200_000)

    @field_validator("repo")
    @classmethod
    def _reject_repo_traversal(cls, v: str) -> str:
        if ".." in v:
            raise ValueError("repo must not contain '..'")
        return v


class QueueItemResponse(DeathStarModel):
    id: str
    conversation_id: str
    repo: str
    branch: str | None = None
    message: str
    workflow: WorkflowKind
    status: QueueStatus
    created_at: datetime


class AgentSessionResponse(DeathStarModel):
    """Active agent session (runs independently of WebSocket connections)."""

    conversation_id: str
    repo: str
    branch: str | None = None
    workflow: WorkflowKind
    status: Literal["starting", "running", "waiting_permission", "completed", "failed"] = "running"
    started_at: float
    last_active: float


# ---------------------------------------------------------------------------
# Repo Context
# ---------------------------------------------------------------------------


class RepoContextResponse(DeathStarModel):
    branch: str
    recent_commits: list[str]
    claude_md: str | None = None
    file_tree: list[str]
    conflict_files: list[str] = []
    branch_switched_from: str | None = None
