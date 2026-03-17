from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _load_dotenv(project_root: Path) -> None:
    dotenv_path = project_root / ".env"
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        stripped_value = value.strip()
        if len(stripped_value) >= 2 and stripped_value[0] == stripped_value[-1] and stripped_value[0] in ('"', "'"):
            stripped_value = stripped_value[1:-1]
        os.environ.setdefault(key.strip(), stripped_value)


def find_project_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()

    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").exists() and (
            candidate / "terraform" / "environments" / "aws-ec2"
        ).exists():
            return candidate

    raise RuntimeError("unable to locate the DeathStar project root")


@dataclass(frozen=True)
class CLIConfig:
    project_root: Path
    terraform_dir: Path
    aws_profile: str | None
    region: str
    project_name: str
    instance_type: str
    root_volume_size_gb: int
    data_volume_size_gb: int
    openai_parameter_name: str
    anthropic_parameter_name: str
    google_parameter_name: str
    vertex_parameter_name: str
    vertex_project_id: str
    vertex_location: str
    github_parameter_name: str
    api_token_parameter_name: str
    create_backup_bucket: bool
    backup_bucket_name: str
    force_destroy_backup_bucket: bool
    enable_web_ui: bool
    web_ui_port: int
    web_ui_allowed_cidrs: list[str]
    git_author_name: str
    git_author_email: str
    enable_tailscale: bool
    enable_tailscale_ssh: bool
    tailscale_auth_parameter_name: str
    tailscale_hostname: str
    tailscale_advertise_tags: list[str]
    remote_transport: str
    connect_transport: str
    github_app_client_id: str | None
    tailscale_oauth_client_id: str | None

    @classmethod
    def load(cls, start: Path | None = None) -> "CLIConfig":
        project_root = find_project_root(start)
        _load_dotenv(project_root)

        terraform_dir = project_root / os.getenv(
            "DEATHSTAR_TERRAFORM_DIR", "terraform/environments/aws-ec2"
        )

        return cls(
            project_root=project_root,
            terraform_dir=terraform_dir,
            aws_profile=os.getenv("DEATHSTAR_AWS_PROFILE"),
            region=os.getenv("DEATHSTAR_REGION", "us-west-1"),
            project_name=os.getenv("DEATHSTAR_PROJECT_NAME", "deathstar"),
            instance_type=os.getenv("DEATHSTAR_INSTANCE_TYPE", "t3.large"),
            root_volume_size_gb=int(os.getenv("DEATHSTAR_ROOT_VOLUME_SIZE_GB", "30")),
            data_volume_size_gb=int(os.getenv("DEATHSTAR_DATA_VOLUME_SIZE_GB", "200")),
            openai_parameter_name=os.getenv(
                "DEATHSTAR_OPENAI_PARAMETER_NAME", "/deathstar/providers/openai/api_key"
            ),
            anthropic_parameter_name=os.getenv(
                "DEATHSTAR_ANTHROPIC_PARAMETER_NAME",
                "/deathstar/providers/anthropic/api_key",
            ),
            google_parameter_name=os.getenv(
                "DEATHSTAR_GOOGLE_PARAMETER_NAME", "/deathstar/providers/google/api_key"
            ),
            vertex_parameter_name=os.getenv(
                "DEATHSTAR_VERTEX_PARAMETER_NAME",
                "/deathstar/providers/vertex/service_account_key",
            ),
            vertex_project_id=os.getenv("DEATHSTAR_VERTEX_PROJECT_ID", ""),
            vertex_location=os.getenv("DEATHSTAR_VERTEX_LOCATION", "us-central1"),
            github_parameter_name=os.getenv(
                "DEATHSTAR_GITHUB_PARAMETER_NAME", "/deathstar/integrations/github/token"
            ),
            api_token_parameter_name=os.getenv(
                "DEATHSTAR_API_TOKEN_PARAMETER_NAME", "/deathstar/api_token"
            ),
            create_backup_bucket=_parse_bool(os.getenv("DEATHSTAR_CREATE_BACKUP_BUCKET")),
            backup_bucket_name=os.getenv("DEATHSTAR_BACKUP_BUCKET_NAME", ""),
            force_destroy_backup_bucket=_parse_bool(
                os.getenv("DEATHSTAR_FORCE_DESTROY_BACKUP_BUCKET")
            ),
            enable_web_ui=_parse_bool(os.getenv("DEATHSTAR_ENABLE_WEB_UI")),
            web_ui_port=int(os.getenv("DEATHSTAR_WEB_UI_PORT", "8443")),
            web_ui_allowed_cidrs=_parse_csv(os.getenv("DEATHSTAR_WEB_UI_ALLOWED_CIDRS")),
            git_author_name=os.getenv("DEATHSTAR_GIT_AUTHOR_NAME", "DeathStar"),
            git_author_email=os.getenv("DEATHSTAR_GIT_AUTHOR_EMAIL", "deathstar@local"),
            enable_tailscale=_parse_bool(os.getenv("DEATHSTAR_ENABLE_TAILSCALE"), default=True),
            enable_tailscale_ssh=_parse_bool(
                os.getenv("DEATHSTAR_ENABLE_TAILSCALE_SSH"), default=True
            ),
            tailscale_auth_parameter_name=os.getenv(
                "DEATHSTAR_TAILSCALE_AUTH_PARAMETER_NAME",
                "/deathstar/integrations/tailscale/auth_key",
            ),
            tailscale_hostname=os.getenv(
                "DEATHSTAR_TAILSCALE_HOSTNAME",
                os.getenv("DEATHSTAR_PROJECT_NAME", "deathstar"),
            ),
            tailscale_advertise_tags=_parse_csv(
                os.getenv("DEATHSTAR_TAILSCALE_ADVERTISE_TAGS")
            ),
            remote_transport=os.getenv("DEATHSTAR_REMOTE_TRANSPORT", "auto").strip().lower(),
            connect_transport=os.getenv("DEATHSTAR_CONNECT_TRANSPORT", "auto").strip().lower(),
            github_app_client_id=os.getenv("DEATHSTAR_GITHUB_APP_CLIENT_ID") or None,
            tailscale_oauth_client_id=os.getenv("DEATHSTAR_TAILSCALE_OAUTH_CLIENT_ID") or None,
        )

    def __post_init__(self) -> None:
        if not re.match(r"^[a-zA-Z0-9_-]+$", self.project_name):
            raise ValueError(
                f"DEATHSTAR_PROJECT_NAME must be alphanumeric, hyphens, or underscores: {self.project_name}"
            )
        if not re.match(r"^[a-z]{2}-[a-z]+-\d+$", self.region):
            raise ValueError(f"DEATHSTAR_REGION does not look like a valid AWS region: {self.region}")
