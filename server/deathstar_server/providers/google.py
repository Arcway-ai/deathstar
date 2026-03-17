from __future__ import annotations

from typing import Any

import httpx

from deathstar_server.providers.base import (
    BaseProvider,
    ProviderResult,
    ensure_text,
    extract_candidate_text,
    normalize_client_error,
    normalize_http_error,
)
from deathstar_shared.models import ProviderName, UsageMetrics


class GoogleProvider(BaseProvider):
    @property
    def name(self) -> ProviderName:
        return ProviderName.GOOGLE

    async def generate_text(
        self,
        *,
        prompt: str,
        model: str | None,
        system: str | None,
        timeout_seconds: int,
    ) -> ProviderResult:
        api_key = self.require_api_key()
        selected_model = model or self.default_model

        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/models/{selected_model}:generateContent",
                    json=payload,
                    headers={
                        "content-type": "application/json",
                        "x-goog-api-key": api_key,
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
