from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx

from deathstar_server.errors import AppError
from deathstar_server.providers.base import (
    BaseProvider,
    ProviderResult,
    ensure_text,
    extract_candidate_text,
    normalize_client_error,
    normalize_http_error,
)
from deathstar_shared.models import ErrorCode, ProviderName, UsageMetrics

logger = logging.getLogger(__name__)

_VERTEX_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


class VertexProvider(BaseProvider):
    """Vertex AI provider supporting multiple GCP auth methods.

    Authentication (in priority order):
      1. Inline credential JSON via DEATHSTAR_VERTEX_SERVICE_ACCOUNT_KEY
         (can be a service account key OR a Workload Identity Federation config)
      2. GOOGLE_APPLICATION_CREDENTIALS file (SA key or WIF config written by bootstrap)
      3. google.auth.default() (ADC, metadata server, etc.)

    All three paths use the google-auth library which auto-detects the credential
    type from the JSON ``type`` field (``service_account``, ``external_account``, etc.).
    """

    def __init__(
        self,
        *,
        project_id: str | None,
        location: str,
        credential_json: str | None,
        default_model: str,
    ) -> None:
        self._project_id = project_id
        self._location = location
        self._credential_json = credential_json
        self._credentials: Any = None
        self._cached_token: str | None = None
        self._token_expiry: float = 0.0
        super().__init__(
            api_key=credential_json,
            default_model=default_model,
            base_url=self._build_base_url(project_id, location),
        )

    @staticmethod
    def _build_base_url(project_id: str | None, location: str) -> str:
        if not project_id:
            return "https://unset.googleapis.com"
        return (
            f"https://{location}-aiplatform.googleapis.com/v1"
            f"/projects/{project_id}/locations/{location}/publishers/google/models"
        )

    @property
    def name(self) -> ProviderName:
        return ProviderName.VERTEX

    @property
    def configured(self) -> bool:
        return bool(self._project_id)

    def _require_configured(self) -> None:
        if not self._project_id:
            raise AppError(
                ErrorCode.PROVIDER_NOT_CONFIGURED,
                "vertex is not configured: DEATHSTAR_VERTEX_PROJECT_ID is not set",
                status_code=400,
            )

    def _load_credentials(self) -> Any:
        """Load GCP credentials, trying inline JSON first then ADC."""
        if self._credentials is not None:
            return self._credentials

        import google.auth

        if self._credential_json:
            info = json.loads(self._credential_json)
            cred_type = info.get("type", "")

            if cred_type == "service_account":
                from google.oauth2.service_account import Credentials

                self._credentials = Credentials.from_service_account_info(
                    info, scopes=_VERTEX_SCOPES
                )
            elif cred_type == "external_account":
                from google.auth import identity_pool

                self._credentials = identity_pool.Credentials.from_info(info)
                self._credentials = self._credentials.with_scopes(_VERTEX_SCOPES)
            else:
                raise AppError(
                    ErrorCode.PROVIDER_NOT_CONFIGURED,
                    f"vertex credential JSON has unsupported type: {cred_type!r}. "
                    "Expected 'service_account' or 'external_account' (WIF).",
                    status_code=400,
                )
        else:
            # Fall back to Application Default Credentials
            # (GOOGLE_APPLICATION_CREDENTIALS file, metadata server, etc.)
            try:
                self._credentials, _ = google.auth.default(scopes=_VERTEX_SCOPES)
            except google.auth.exceptions.DefaultCredentialsError as exc:
                raise AppError(
                    ErrorCode.PROVIDER_NOT_CONFIGURED,
                    "vertex is not configured: no GCP credentials found. "
                    "Set GOOGLE_APPLICATION_CREDENTIALS or store a credential config "
                    "via 'deathstar secrets put --provider vertex'.",
                    status_code=400,
                ) from exc

        return self._credentials

    async def _get_access_token(self) -> str:
        """Get an OAuth2 access token, refreshing if expired."""
        if self._cached_token and time.time() < self._token_expiry:
            return self._cached_token

        credentials = self._load_credentials()
        await asyncio.to_thread(self._refresh_credentials, credentials)
        self._cached_token = credentials.token
        # Use actual expiry if available, otherwise default to 59 minutes
        if hasattr(credentials, "expiry") and credentials.expiry is not None:
            self._token_expiry = credentials.expiry.timestamp() - 60
        else:
            self._token_expiry = time.time() + 3540
        return self._cached_token

    @staticmethod
    def _refresh_credentials(credentials) -> None:
        from google.auth.transport.requests import Request
        credentials.refresh(Request())

    async def generate_text(
        self,
        *,
        prompt: str,
        model: str | None,
        system: str | None,
        timeout_seconds: int,
    ) -> ProviderResult:
        self._require_configured()
        selected_model = model or self.default_model

        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        access_token = await self._get_access_token()
        url = f"{self.base_url}/{selected_model}:generateContent"

        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {access_token}",
                    },
                )
        except httpx.HTTPError as exc:
            raise normalize_client_error(self.name, exc) from exc

        if response.status_code >= 400:
            raise normalize_http_error(self.name, response)

        data = response.json()
        text = extract_candidate_text(data.get("candidates", []))
        usage = data.get("usageMetadata", {})

        return ProviderResult(
            text=ensure_text(text, self.name),
            model=selected_model,
            usage=UsageMetrics(
                input_tokens=usage.get("promptTokenCount"),
                output_tokens=usage.get("candidatesTokenCount"),
                total_tokens=usage.get("totalTokenCount"),
            ),
            remote_response_id=data.get("responseId"),
        )
