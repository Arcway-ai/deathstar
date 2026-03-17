from __future__ import annotations

import asyncio
import logging

from deathstar_server.config import Settings
from deathstar_server.errors import AppError
from deathstar_server.providers.anthropic import AnthropicProvider
from deathstar_server.providers.base import ProviderResult
from deathstar_server.providers.google import GoogleProvider
from deathstar_server.providers.openai import OpenAIProvider
from deathstar_server.providers.vertex import VertexProvider
from deathstar_shared.models import ProviderName, ProviderStatus

logger = logging.getLogger(__name__)


class ProviderRegistry:
    def __init__(self, settings: Settings) -> None:
        self.providers = {
            ProviderName.OPENAI: OpenAIProvider(
                api_key=settings.openai_api_key,
                default_model=settings.default_openai_model,
                base_url=settings.openai_api_base_url,
            ),
            ProviderName.ANTHROPIC: AnthropicProvider(
                api_key=settings.anthropic_api_key,
                default_model=settings.default_anthropic_model,
                base_url=settings.anthropic_api_base_url,
                api_version=settings.anthropic_api_version,
            ),
            ProviderName.GOOGLE: GoogleProvider(
                api_key=settings.google_api_key,
                default_model=settings.default_google_model,
                base_url=settings.google_api_base_url,
            ),
            ProviderName.VERTEX: VertexProvider(
                project_id=settings.vertex_project_id,
                location=settings.vertex_location,
                credential_json=settings.vertex_service_account_key,
                default_model=settings.default_vertex_model,
            ),
        }

    def status(self) -> dict[str, ProviderStatus]:
        return {
            provider.value: ProviderStatus(
                configured=adapter.configured,
                default_model=adapter.default_model,
            )
            for provider, adapter in self.providers.items()
        }

    async def generate_text(
        self,
        *,
        provider: ProviderName,
        prompt: str,
        model: str | None,
        system: str | None,
        timeout_seconds: int,
        max_retries: int = 2,
    ) -> ProviderResult:
        adapter = self.providers[provider]
        last_error: Exception | None = None

        for attempt in range(1 + max_retries):
            try:
                return await adapter.generate_text(
                    prompt=prompt,
                    model=model,
                    system=system,
                    timeout_seconds=timeout_seconds,
                )
            except AppError as exc:
                last_error = exc
                if not exc.retryable or attempt >= max_retries:
                    raise
                delay = 2 ** attempt  # 1s, 2s
                logger.warning(
                    "provider %s returned retryable error (attempt %d/%d), retrying in %ds: %s",
                    provider.value,
                    attempt + 1,
                    1 + max_retries,
                    delay,
                    exc.message,
                )
                await asyncio.sleep(delay)

        raise last_error  # type: ignore[misc]
