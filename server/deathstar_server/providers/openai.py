from __future__ import annotations

from typing import Any

import httpx

from deathstar_server.providers.base import (
    BaseProvider,
    ProviderResult,
    as_usage,
    ensure_text,
    normalize_client_error,
    normalize_http_error,
)
from deathstar_shared.models import ProviderName


class OpenAIProvider(BaseProvider):
    @property
    def name(self) -> ProviderName:
        return ProviderName.OPENAI

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

        payload: dict[str, Any] = {"model": selected_model, "input": prompt}
        if system:
            payload["instructions"] = system

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/responses",
                    json=payload,
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            raise normalize_client_error(self.name, exc) from exc

        if response.status_code >= 400:
            raise normalize_http_error(self.name, response)

        data = response.json()
        text = data.get("output_text") or _extract_output_text(data.get("output", []))

        return ProviderResult(
            text=ensure_text(text, self.name),
            model=str(data.get("model", selected_model)),
            usage=as_usage(
                data.get("usage", {}),
                input_key="input_tokens",
                output_key="output_tokens",
                total_key="total_tokens",
            ),
            remote_response_id=data.get("id"),
        )


def _extract_output_text(items: list[dict[str, Any]]) -> str | None:
    parts: list[str] = []
    for item in items:
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                parts.append(str(content["text"]))
    return "\n".join(parts) if parts else None
