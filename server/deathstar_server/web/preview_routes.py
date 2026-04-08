from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy.exc import IntegrityError

from sqlmodel import Session, select

from deathstar_server.app_state import (
    engine as db_engine,
    git_service,
    github_service,
    render_preview,
)
from deathstar_server.db.models import PreviewDeployment
from deathstar_server.errors import AppError
from deathstar_shared.models import (
    CreatePreviewRequest,
    ErrorCode,
    PreviewDeploymentResponse,
    PreviewProvider as PreviewProviderEnum,
    PreviewStatus,
)

logger = logging.getLogger(__name__)

preview_router = APIRouter(prefix="/web/api")


def _to_response(row: PreviewDeployment) -> PreviewDeploymentResponse:
    return PreviewDeploymentResponse(
        id=row.id,
        repo=row.repo,
        branch=row.branch,
        provider=row.provider,
        provider_service_id=row.provider_service_id,
        status=row.status,
        preview_url=row.preview_url,
        error_message=row.error_message,
        created_at=datetime.fromisoformat(row.created_at),
        updated_at=datetime.fromisoformat(row.updated_at),
    )


def _get_provider(provider: PreviewProviderEnum):
    """Resolve a provider enum to the concrete provider instance."""
    if provider == PreviewProviderEnum.RENDER:
        return render_preview
    raise AppError(
        ErrorCode.INVALID_REQUEST,
        f"Preview provider '{provider}' is not supported yet",
        status_code=400,
    )


@preview_router.post(
    "/repos/{name}/previews",
    response_model=PreviewDeploymentResponse,
)
async def create_preview(name: str, body: CreatePreviewRequest):
    """Create a preview deployment for a branch."""
    repo_root = git_service.resolve_target(name)
    provider = _get_provider(body.provider)

    # Application-level duplicate check (fast-path rejection).
    # The partial unique index (uq_preview_active_repo_branch_provider) enforces
    # this atomically at the DB level to close the TOCTOU race window.
    with Session(db_engine) as session:
        existing = session.exec(
            select(PreviewDeployment)
            .where(PreviewDeployment.repo == name)
            .where(PreviewDeployment.branch == body.branch)
            .where(PreviewDeployment.provider == body.provider)
            .where(PreviewDeployment.status.notin_([  # type: ignore[union-attr]
                PreviewStatus.DESTROYED.value,
                PreviewStatus.FAILED.value,
            ]))
        ).first()
        if existing:
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                f"An active preview already exists for {name}/{body.branch} "
                f"(id={existing.id}, status={existing.status})",
                status_code=409,
            )

    # Resolve GitHub owner/repo from the local git remote
    repo_full_name = github_service.get_repo_full_name(repo_root)

    # Generate a short, unique service name for the preview.
    # Sanitize branch name: Render requires alphanumeric + hyphens only.
    safe_branch = re.sub(r"[^a-zA-Z0-9-]", "-", body.branch).strip("-")
    short_id = uuid.uuid4().hex[:6]
    service_name = f"preview-{name}-{safe_branch}-{short_id}"[:50]

    result = await provider.create_preview(
        repo_full_name=repo_full_name,
        branch=body.branch,
        service_name=service_name,
    )

    now = datetime.now(timezone.utc).isoformat()
    row = PreviewDeployment(
        id=str(uuid.uuid4()),
        repo=name,
        branch=body.branch,
        provider=body.provider,
        provider_service_id=result.provider_service_id,
        status=result.status,
        preview_url=result.preview_url,
        created_at=now,
        updated_at=now,
    )

    try:
        with Session(db_engine) as session:
            session.add(row)
            session.commit()
            session.refresh(row)
    except IntegrityError:
        # Concurrent request won the race — clean up the Render service we just
        # created, then return 409 so the caller retries or fetches the existing
        # preview.
        logger.warning(
            "TOCTOU race: duplicate preview for %s/%s/%s — cleaning up Render service %s",
            name, body.branch, body.provider, result.provider_service_id,
        )
        await provider.delete_preview(result.provider_service_id)
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            f"An active preview already exists for {name}/{body.branch} "
            "(concurrent request won the race)",
            status_code=409,
        )

    logger.info(
        "Created preview deployment %s for %s/%s via %s",
        row.id, name, body.branch, body.provider,
    )
    return _to_response(row)


@preview_router.get(
    "/repos/{name}/previews",
    response_model=list[PreviewDeploymentResponse],
)
def list_previews(name: str):
    """List preview deployments for a repo (excludes destroyed)."""
    with Session(db_engine) as session:
        stmt = (
            select(PreviewDeployment)
            .where(PreviewDeployment.repo == name)
            .where(PreviewDeployment.status != PreviewStatus.DESTROYED.value)
            .order_by(PreviewDeployment.created_at.desc())
        )
        rows = session.exec(stmt).all()
        return [_to_response(r) for r in rows]


@preview_router.get(
    "/repos/{name}/previews/{preview_id}",
    response_model=PreviewDeploymentResponse,
)
async def get_preview(name: str, preview_id: str):
    """Get preview status (refreshes from provider)."""
    with Session(db_engine) as session:
        row = session.get(PreviewDeployment, preview_id)
        if not row or row.repo != name:
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                f"Preview deployment '{preview_id}' not found",
                status_code=404,
            )

        # Only refresh from provider if the preview is still active
        if row.status in (
            PreviewStatus.PENDING.value,
            PreviewStatus.BUILDING.value,
            PreviewStatus.LIVE.value,
        ):
            provider = _get_provider(row.provider)
            result = await provider.get_status(row.provider_service_id)
            row.status = result.status
            row.preview_url = result.preview_url or row.preview_url
            row.error_message = result.error_message
            row.updated_at = datetime.now(timezone.utc).isoformat()
            session.add(row)
            session.commit()
            session.refresh(row)

        return _to_response(row)


@preview_router.delete("/repos/{name}/previews/{preview_id}")
async def delete_preview(name: str, preview_id: str):
    """Tear down a preview deployment."""
    with Session(db_engine) as session:
        row = session.get(PreviewDeployment, preview_id)
        if not row or row.repo != name:
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                f"Preview deployment '{preview_id}' not found",
                status_code=404,
            )

        if row.status == PreviewStatus.DESTROYED.value:
            return {"status": "already_destroyed"}

        provider = _get_provider(row.provider)
        await provider.delete_preview(row.provider_service_id)

        row.status = PreviewStatus.DESTROYED.value
        row.updated_at = datetime.now(timezone.utc).isoformat()
        session.add(row)
        session.commit()

    logger.info("Destroyed preview deployment %s", preview_id)
    return {"status": "destroyed"}


@preview_router.get("/preview-providers")
async def list_preview_providers():
    """Return which preview providers are configured."""
    return {
        "providers": {
            "render": await render_preview.is_configured(),
        },
    }
