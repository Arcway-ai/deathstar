from __future__ import annotations

import getpass
import sys
from dataclasses import dataclass
from enum import Enum

import boto3
import typer
from botocore.exceptions import BotoCoreError, ClientError, ProfileNotFound

from deathstar_cli.config import CLIConfig
from deathstar_shared.models import ProviderName


class IntegrationName(str, Enum):
    TAILSCALE = "tailscale"
    GITHUB = "github"
    DATABASE = "database"


@dataclass(frozen=True)
class SecretTarget:
    label: str
    parameter_name: str


def _ssm_client(config: CLIConfig, region: str):
    session_kwargs: dict[str, str] = {"region_name": region}
    if config.aws_profile:
        session_kwargs["profile_name"] = config.aws_profile

    try:
        session = boto3.Session(**session_kwargs)
    except ProfileNotFound as exc:
        raise RuntimeError(f"AWS profile not found: {config.aws_profile}") from exc

    return session.client("ssm")


def provider_target(config: CLIConfig, provider: ProviderName) -> SecretTarget:
    mapping = {
        ProviderName.ANTHROPIC: SecretTarget(
            label="Anthropic API key",
            parameter_name=config.anthropic_parameter_name,
        ),
    }
    return mapping[provider]


def integration_target(config: CLIConfig, integration: IntegrationName) -> SecretTarget:
    mapping = {
        IntegrationName.TAILSCALE: SecretTarget(
            label="Tailscale auth key",
            parameter_name=config.tailscale_auth_parameter_name,
        ),
        IntegrationName.GITHUB: SecretTarget(
            label="GitHub token",
            parameter_name=config.github_parameter_name,
        ),
        IntegrationName.DATABASE: SecretTarget(
            label="Database password",
            parameter_name=config.db_password_parameter_name,
        ),
    }
    return mapping[integration]


def resolve_secret_target(
    config: CLIConfig,
    provider: ProviderName | None = None,
    integration: IntegrationName | None = None,
    name: str | None = None,
) -> SecretTarget:
    selected = [provider is not None, integration is not None, bool(name)]
    if sum(selected) != 1:
        raise typer.BadParameter(
            "choose exactly one of --provider, --integration, or --name"
        )

    if provider is not None:
        return provider_target(config, provider)
    if integration is not None:
        return integration_target(config, integration)
    return SecretTarget(label="secret value", parameter_name=str(name))


def bootstrap_targets(
    config: CLIConfig,
    include_tailscale: bool,
    include_github: bool,
    include_database: bool = True,
) -> list[SecretTarget]:
    targets = [
        provider_target(config, ProviderName.ANTHROPIC),
    ]

    if include_database:
        targets.append(integration_target(config, IntegrationName.DATABASE))
    if include_tailscale:
        targets.append(integration_target(config, IntegrationName.TAILSCALE))
    if include_github:
        targets.append(integration_target(config, IntegrationName.GITHUB))

    return targets


def _read_secret_from_stdin() -> str:
    if sys.stdin.isatty():
        raise typer.BadParameter(
            "--stdin expects piped input; omit it to use the hidden prompt"
        )

    value = sys.stdin.read().rstrip("\r\n")
    if not value:
        raise typer.BadParameter("stdin did not contain a secret value")
    return value


def _read_secret_from_file(path: str) -> str:
    from pathlib import Path

    file_path = Path(path).expanduser().resolve()
    if not file_path.is_file():
        raise typer.BadParameter(f"file not found: {file_path}")

    value = file_path.read_text(encoding="utf-8").strip()
    if not value:
        raise typer.BadParameter(f"file is empty: {file_path}")
    return value


def prompt_for_secret(label: str, allow_empty: bool = False) -> str | None:
    while True:
        prompt_suffix = " (leave blank to skip)" if allow_empty else ""
        first = getpass.getpass(f"{label}{prompt_suffix}: ")
        if not first:
            if allow_empty:
                return None
            typer.echo("Secret value cannot be empty.", err=True)
            continue

        confirmation = getpass.getpass(f"Confirm {label}: ")
        if first == confirmation:
            return first

        typer.echo("Secret values did not match. Try again.", err=True)


def _parameter_exists(ssm_client, parameter_name: str) -> bool:
    try:
        ssm_client.get_parameter(Name=parameter_name, WithDecryption=False)
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ParameterNotFound":
            return False
        raise RuntimeError(
            _format_client_error("check parameter", parameter_name, exc)
        ) from exc


def _format_client_error(action: str, parameter_name: str, exc: ClientError) -> str:
    error = exc.response.get("Error", {})
    code = error.get("Code", "unknown")
    message = error.get("Message", str(exc))
    return f"failed to {action} for {parameter_name}: {code}: {message}"


def put_secret_value(
    config: CLIConfig,
    region: str,
    target: SecretTarget,
    value: str,
    force: bool,
) -> tuple[str, int | None]:
    try:
        ssm_client = _ssm_client(config, region)
        exists = _parameter_exists(ssm_client, target.parameter_name)

        if exists and not force:
            if not typer.confirm(
                f"{target.parameter_name} already exists in {region}. Overwrite it?"
            ):
                raise typer.Exit(code=1)

        response = ssm_client.put_parameter(
            Name=target.parameter_name,
            Value=value,
            Type="SecureString",
            Overwrite=exists,
        )
    except typer.Exit:
        raise
    except ClientError as exc:
        raise RuntimeError(
            _format_client_error("store secret", target.parameter_name, exc)
        ) from exc
    except BotoCoreError as exc:
        raise RuntimeError(f"failed to store secret in SSM: {exc}") from exc

    return ("updated" if exists else "created", response.get("Version"))


def prompt_and_store_secret(
    config: CLIConfig,
    region: str,
    target: SecretTarget,
    force: bool,
    stdin: bool = False,
    file: str | None = None,
) -> tuple[str, int | None]:
    if file:
        value: str | None = _read_secret_from_file(file)
    elif stdin:
        value = _read_secret_from_stdin()
    else:
        value = prompt_for_secret(target.label)
    if value is None:
        raise typer.BadParameter("secret value cannot be empty")
    return put_secret_value(config, region, target, value, force=force)
