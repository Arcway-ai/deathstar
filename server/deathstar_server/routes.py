from __future__ import annotations

from fastapi import APIRouter, Query

from deathstar_server.app_state import backup_service, settings, workflow_service
from deathstar_shared.models import (
    BackupRequest,
    BackupResponse,
    LogsResponse,
    RestoreRequest,
    RestoreResponse,
    StatusResponse,
    WorkflowKind,
    WorkflowRequest,
    WorkflowResponse,
)
from deathstar_shared.version import VERSION, full_version

router = APIRouter(prefix="/v1")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": full_version()}


@router.get("/status", response_model=StatusResponse)
def status() -> StatusResponse:
    return StatusResponse(
        service="healthy",
        version=VERSION,
        workspace_root=str(settings.workspace_root),
        projects_root=str(settings.projects_root),
        log_path=str(settings.log_path),
        backup_directory=str(settings.backup_directory),
        backup_bucket=settings.backup_bucket,
        github_prs_enabled=bool(settings.github_token),
        preferred_transport="tailscale" if settings.tailscale_enabled else "ssm",
        tailscale_enabled=settings.tailscale_enabled,
        tailscale_hostname=settings.tailscale_hostname,
        ssh_user=settings.ssh_user,
        providers=workflow_service.providers.status(),
        workflows=[
            WorkflowKind.PROMPT,
            WorkflowKind.PATCH,
            WorkflowKind.PR,
            WorkflowKind.REVIEW,
        ],
    )


@router.post("/run", response_model=WorkflowResponse)
async def run(request: WorkflowRequest) -> WorkflowResponse:
    return await workflow_service.execute(request)


@router.get("/logs", response_model=LogsResponse)
def logs(tail: int = Query(default=200, ge=1, le=10000)) -> LogsResponse:
    return LogsResponse(lines=backup_service.latest_log_lines(tail))


@router.post("/backup", response_model=BackupResponse)
def backup(request: BackupRequest) -> BackupResponse:
    return backup_service.create_backup(request.label)


@router.post("/restore", response_model=RestoreResponse)
def restore(request: RestoreRequest) -> RestoreResponse:
    return backup_service.restore(request.backup_id)
