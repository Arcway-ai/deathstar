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
    github_token: str | None
    tailscale_enabled: bool
    tailscale_hostname: str | None
    ssh_user: str
    api_token: str | None


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
    )
