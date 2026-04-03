from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path


def _optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logging.getLogger(__name__).warning(
            "Invalid integer for %s=%r, using default %d", name, raw, default,
        )
        return default


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
    github_token: str | None
    tailscale_enabled: bool
    tailscale_hostname: str | None
    ssh_user: str
    api_token: str | None
    github_webhook_secret: str | None
    github_poll_interval_seconds: int
    max_worktrees_per_repo: int
    max_total_worktrees: int
    database_url: str


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
        github_token=_optional(os.getenv("GITHUB_TOKEN")),
        tailscale_enabled=os.getenv("DEATHSTAR_TAILSCALE_ENABLED", "false").strip().lower()
        in {"1", "true", "yes", "on"},
        tailscale_hostname=_optional(os.getenv("DEATHSTAR_TAILSCALE_HOSTNAME")),
        ssh_user=os.getenv("DEATHSTAR_SSH_USER", "ubuntu"),
        api_token=_optional(os.getenv("DEATHSTAR_API_TOKEN")),
        github_webhook_secret=_optional(os.getenv("GITHUB_WEBHOOK_SECRET")),
        github_poll_interval_seconds=_int_env("GITHUB_POLL_INTERVAL", 10),
        max_worktrees_per_repo=_int_env("DEATHSTAR_MAX_WORKTREES_PER_REPO", 6),
        max_total_worktrees=_int_env("DEATHSTAR_MAX_TOTAL_WORKTREES", 16),
        database_url=os.getenv(
            "DEATHSTAR_DATABASE_URL",
            "postgresql://deathstar:deathstar@localhost:5432/deathstar",
        ),
    )
