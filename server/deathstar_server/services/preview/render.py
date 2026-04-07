from __future__ import annotations

import asyncio
import logging

import httpx

from deathstar_server.config import Settings
from deathstar_server.errors import AppError
from deathstar_server.services.preview.base import PreviewProvider, PreviewResult
from deathstar_shared.models import ErrorCode

logger = logging.getLogger(__name__)

RENDER_BASE_URL = "https://api.render.com/v1"

# Map Render deploy statuses to our PreviewStatus values.
_RENDER_STATUS_MAP: dict[str, str] = {
    "created": "pending",
    "build_in_progress": "building",
    "update_in_progress": "building",
    "live": "live",
    "deactivated": "destroyed",
    "build_failed": "failed",
    "update_failed": "failed",
    "canceled": "failed",
    "pre_deploy_in_progress": "building",
    "pre_deploy_failed": "failed",
}


class RenderPreviewProvider(PreviewProvider):
    """Render.com preview deployment provider.

    Creates a throwaway web service via the Render API for the target branch.
    The service is deleted when the preview is torn down.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._owner_id = settings.render_owner_id

    def _require_key(self) -> str:
        if not self._settings.render_api_key:
            raise AppError(
                ErrorCode.INTEGRATION_NOT_CONFIGURED,
                "Render integration is not configured — set RENDER_API_KEY",
                status_code=400,
            )
        return self._settings.render_api_key

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._require_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def is_configured(self) -> bool:
        return bool(self._settings.render_api_key)

    async def create_preview(
        self,
        *,
        repo_full_name: str,
        branch: str,
        service_name: str,
    ) -> PreviewResult:
        """Create a new Render web service for the branch.

        Uses ``POST /v1/services`` to create a throwaway service pointing at
        the target branch.  Render will auto-build on creation.
        """
        payload: dict = {
            "type": "web_service",
            "name": service_name,
            "repo": f"https://github.com/{repo_full_name}",
            "branch": branch,
            "autoDeploy": "yes",
        }
        if self._owner_id:
            payload["ownerId"] = self._owner_id

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{RENDER_BASE_URL}/services",
                headers=self._headers(),
                json=payload,
                timeout=30.0,
            )

        if resp.status_code >= 400:
            body = resp.text[:500]
            logger.error("Render API error creating service: %s", body)
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                f"Render API error ({resp.status_code}): {body}",
                status_code=502,
            )

        data = resp.json()
        # Render wraps the response in a {"service": {...}} envelope.
        service = data.get("service", data)
        service_id = service["id"]
        url = service.get("serviceDetails", {}).get("url")

        logger.info(
            "Created Render preview service %s for %s/%s",
            service_id, repo_full_name, branch,
        )

        return PreviewResult(
            provider_service_id=service_id,
            preview_url=f"https://{url}" if url and not url.startswith("http") else url,
            status="pending",
        )

    async def get_status(self, provider_service_id: str) -> PreviewResult:
        """Fetch the latest deploy status for a Render service."""
        async with httpx.AsyncClient() as client:
            headers = self._headers()
            # Fetch service info and latest deploy in parallel
            svc_resp, deploy_resp = await asyncio.gather(
                client.get(
                    f"{RENDER_BASE_URL}/services/{provider_service_id}",
                    headers=headers,
                    timeout=15.0,
                ),
                client.get(
                    f"{RENDER_BASE_URL}/services/{provider_service_id}/deploys",
                    headers=headers,
                    params={"limit": "1"},
                    timeout=15.0,
                ),
            )

        if svc_resp.status_code == 404:
            return PreviewResult(
                provider_service_id=provider_service_id,
                status="destroyed",
            )

        if svc_resp.status_code >= 400:
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                f"Render API error fetching service: {svc_resp.text[:300]}",
                status_code=502,
            )

        service = svc_resp.json()
        url = service.get("serviceDetails", {}).get("url")

        status = "pending"
        error_msg: str | None = None
        if deploy_resp.status_code < 400:
            deploys = deploy_resp.json()
            if isinstance(deploys, list) and deploys:
                deploy = deploys[0].get("deploy", deploys[0])
                render_status = deploy.get("status", "")
                status = _RENDER_STATUS_MAP.get(render_status, "pending")
                if status == "failed":
                    error_msg = f"Render deploy status: {render_status}"

        return PreviewResult(
            provider_service_id=provider_service_id,
            preview_url=f"https://{url}" if url and not url.startswith("http") else url,
            status=status,
            error_message=error_msg,
        )

    async def delete_preview(self, provider_service_id: str) -> None:
        """Delete a Render service (tears down the preview)."""
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{RENDER_BASE_URL}/services/{provider_service_id}",
                headers=self._headers(),
                timeout=15.0,
            )

        # 404 is fine — already deleted.
        if resp.status_code >= 400 and resp.status_code != 404:
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                f"Render API error deleting service: {resp.text[:300]}",
                status_code=502,
            )

        logger.info("Deleted Render preview service %s", provider_service_id)
