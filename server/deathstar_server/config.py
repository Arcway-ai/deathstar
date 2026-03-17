from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


@dataclass(frozen=True)
class Settings:
    workspace_root: Path
    projects_root: Path
    log_path: Path
    backup_directory: Path
    backup_bucket: str | None
    backup_s3_prefix: str
    aws_region: str
    log_level: str
    openai_api_key: str | None
    anthropic_api_key: str | None
    google_api_key: str | None
    github_token: str | None
    openai_api_base_url: str
    anthropic_api_base_url: str
    anthropic_api_version: str
    google_api_base_url: str
    vertex_project_id: str | None
    vertex_location: str
    vertex_service_account_key: str | None
    default_openai_model: str
    default_anthropic_model: str
    default_google_model: str
    default_vertex_model: str
    git_author_name: str
    git_author_email: str
    tailscale_enabled: bool
    tailscale_hostname: str | None
    ssh_user: str
    api_token: str | None
    enable_web_ui: bool


def load_settings() -> Settings:
    workspace_root = Path(os.getenv("DEATHSTAR_WORKSPACE_ROOT", "/workspace")).resolve()
    projects_root = Path(os.getenv("DEATHSTAR_PROJECTS_ROOT", str(workspace_root / "projects"))).resolve()
    log_path = Path(
        os.getenv("DEATHSTAR_LOG_PATH", str(workspace_root / "deathstar" / "logs" / "control-api.log"))
    ).resolve()
    backup_directory = Path(
        os.getenv(
            "DEATHSTAR_BACKUP_DIRECTORY",
            str(workspace_root / "deathstar" / "backups"),
        )
    ).resolve()

    return Settings(
        workspace_root=workspace_root,
        projects_root=projects_root,
        log_path=log_path,
        backup_directory=backup_directory,
        backup_bucket=_optional(os.getenv("DEATHSTAR_BACKUP_BUCKET")),
        backup_s3_prefix=os.getenv("DEATHSTAR_BACKUP_S3_PREFIX", "workspace-backups"),
        aws_region=os.getenv("DEATHSTAR_AWS_REGION", "us-west-1"),
        log_level=os.getenv("DEATHSTAR_LOG_LEVEL", "INFO"),
        openai_api_key=_optional(os.getenv("OPENAI_API_KEY")),
        anthropic_api_key=_optional(os.getenv("ANTHROPIC_API_KEY")),
        google_api_key=_optional(os.getenv("GOOGLE_API_KEY")),
        github_token=_optional(os.getenv("GITHUB_TOKEN")),
        openai_api_base_url=os.getenv("DEATHSTAR_OPENAI_API_BASE_URL", "https://api.openai.com/v1"),
        anthropic_api_base_url=os.getenv(
            "DEATHSTAR_ANTHROPIC_API_BASE_URL", "https://api.anthropic.com/v1"
        ),
        anthropic_api_version=os.getenv("DEATHSTAR_ANTHROPIC_API_VERSION", "2023-06-01"),
        google_api_base_url=os.getenv(
            "DEATHSTAR_GOOGLE_API_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
        ),
        vertex_project_id=_optional(os.getenv("DEATHSTAR_VERTEX_PROJECT_ID")),
        vertex_location=os.getenv("DEATHSTAR_VERTEX_LOCATION", "us-central1"),
        vertex_service_account_key=_optional(os.getenv("DEATHSTAR_VERTEX_SERVICE_ACCOUNT_KEY")),
        default_openai_model=os.getenv("DEATHSTAR_DEFAULT_OPENAI_MODEL", "gpt-4o-mini"),
        default_anthropic_model=os.getenv(
            "DEATHSTAR_DEFAULT_ANTHROPIC_MODEL", "claude-sonnet-4-5-20250514"
        ),
        default_google_model=os.getenv("DEATHSTAR_DEFAULT_GOOGLE_MODEL", "gemini-2.0-flash"),
        default_vertex_model=os.getenv("DEATHSTAR_DEFAULT_VERTEX_MODEL", "gemini-2.0-flash"),
        git_author_name=os.getenv("DEATHSTAR_GIT_AUTHOR_NAME", "DeathStar"),
        git_author_email=os.getenv("DEATHSTAR_GIT_AUTHOR_EMAIL", "deathstar@local"),
        tailscale_enabled=os.getenv("DEATHSTAR_TAILSCALE_ENABLED", "false").strip().lower()
        in {"1", "true", "yes", "on"},
        tailscale_hostname=_optional(os.getenv("DEATHSTAR_TAILSCALE_HOSTNAME")),
        ssh_user=os.getenv("DEATHSTAR_SSH_USER", "ec2-user"),
        api_token=_optional(os.getenv("DEATHSTAR_API_TOKEN")),
        enable_web_ui=os.getenv("DEATHSTAR_ENABLE_WEB_UI", "false").strip().lower()
        in {"1", "true", "yes", "on"},
    )
