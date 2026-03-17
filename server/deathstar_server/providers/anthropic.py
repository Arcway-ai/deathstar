from __future__ import annotations

import httpx

from deathstar_server.providers.base import (
    BaseProvider,
    ProviderResult,
    ensure_text,
    normalize_client_error,
    normalize_http_error,
)
from deathstar_shared.models import ProviderName, UsageMetrics

# Max output tokens per model family — use the highest supported value so responses
# are never silently truncated.  Falls back to 16384 for unknown models.
_MAX_TOKENS: dict[str, int] = {
    "claude-opus-4": 32000,
    "claude-sonnet-4": 64000,
    "claude-haiku-4": 16384,
    "claude-3-7-sonnet": 64000,
    "claude-3-5-sonnet": 8192,
    "claude-3-5-haiku": 8192,
    "claude-3-opus": 4096,
    "claude-3-sonnet": 4096,
    "claude-3-haiku": 4096,
}

_DEFAULT_MAX_TOKENS = 16384


def _max_tokens_for_model(model: str) -> int:
    """Return the ideal max_tokens for a given Anthropic model identifier."""
    for prefix, limit in _MAX_TOKENS.items():
        if model.startswith(prefix):
            return limit
    return _DEFAULT_MAX_TOKENS


class AnthropicProvider(BaseProvider):
    def __init__(
        self,
        *,
        api_key: str | None,
        default_model: str,
        base_url: str,
        api_version: str,
    ) -> None:
        super().__init__(api_key=api_key, default_model=default_model, base_url=base_url)
        self.api_version = api_version

    @property
    def name(self) -> ProviderName:
        return ProviderName.ANTHROPIC

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

        payload: dict[str, object] = {
            "model": selected_model,
            "max_tokens": _max_tokens_for_model(selected_model),
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system

        headers = {
            "x-api-key": api_key,
            "anthropic-version": self.api_version,
            "content-type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/messages",
                    json=payload,
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            raise normalize_client_error(self.name, exc) from exc

        if response.status_code >= 400:
            raise normalize_http_error(self.name, response)

        data = response.json()
        text = "\n".join(
            part["text"]
            for part in data.get("content", [])
            if part.get("type") == "text" and part.get("text")
        )
        usage_payload = data.get("usage", {})
        input_tokens = usage_payload.get("input_tokens")
        output_tokens = usage_payload.get("output_tokens")
        total_tokens = None
        if input_tokens is not None and output_tokens is not None:
            total_tokens = int(input_tokens) + int(output_tokens)

        return ProviderResult(
            text=ensure_text(text, self.name),
            model=str(data.get("model", selected_model)),
            usage=UsageMetrics(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
            ),
            remote_response_id=data.get("id"),
        )
