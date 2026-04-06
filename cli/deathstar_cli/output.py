from __future__ import annotations

import json
from typing import Any

import typer

from deathstar_shared.models import (
    BackupResponse,
    LogsResponse,
    RestoreResponse,
    StatusResponse,
)


def validate_output_format(output: str) -> str:
    normalized = output.strip().lower()
    if normalized not in {"text", "json"}:
        raise typer.BadParameter("output must be text or json")
    return normalized


def emit_json(payload: Any) -> None:
    typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))


def emit_status(response: StatusResponse, output: str) -> None:
    if output == "json":
        emit_json(response.model_dump(mode="json"))
        return

    typer.echo(f"service: {response.service}")
    typer.echo(f"version: {response.version}")
    typer.echo(f"workspace_root: {response.workspace_root}")
    typer.echo(f"projects_root: {response.projects_root}")
    typer.echo(f"log_path: {response.log_path}")
    typer.echo(f"backup_directory: {response.backup_directory}")
    typer.echo(f"backup_bucket: {response.backup_bucket or 'disabled'}")
    typer.echo(f"github_prs_enabled: {response.github_prs_enabled}")
    typer.echo(f"preferred_transport: {response.preferred_transport}")
    typer.echo(f"tailscale_enabled: {response.tailscale_enabled}")
    if response.tailscale_hostname:
        typer.echo(f"tailscale_hostname: {response.tailscale_hostname}")
    typer.echo(f"ssh_user: {response.ssh_user}")
    typer.echo("providers:")
    for name, provider in response.providers.items():
        typer.echo(f"  {name}: configured={provider.configured} default_model={provider.default_model}")


def emit_logs(response: LogsResponse, output: str) -> None:
    if output == "json":
        emit_json(response.model_dump(mode="json"))
        return
    typer.echo("\n".join(response.lines))


def emit_backup(response: BackupResponse, output: str) -> None:
    if output == "json":
        emit_json(response.model_dump(mode="json"))
        return
    typer.echo(f"backup_id: {response.backup_id}")
    typer.echo(f"created_at: {response.created_at}")
    typer.echo(f"local_path: {response.local_path}")
    typer.echo(f"s3_uri: {response.s3_uri or 'not uploaded'}")


def emit_restore(response: RestoreResponse, output: str) -> None:
    if output == "json":
        emit_json(response.model_dump(mode="json"))
        return
    typer.echo(f"backup_id: {response.backup_id}")
    typer.echo(f"restored_from: {response.restored_from}")
    typer.echo(f"projects_root: {response.projects_root}")
