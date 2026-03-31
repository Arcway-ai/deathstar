from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable

from deathstar_server.config import Settings
from deathstar_server.errors import AppError
from deathstar_server.providers.anthropic import AnthropicProvider
from deathstar_server.providers.base import (
    Message,
    ProviderResult,
    StreamDelta,
    StreamDone,
    ToolCall,
    ToolDefinition,
    ToolResult,
)
from deathstar_shared.models import ProviderName, ProviderStatus

logger = logging.getLogger(__name__)


class ProviderRegistry:
    def __init__(self, settings: Settings) -> None:
        self.providers = {
            ProviderName.ANTHROPIC: AnthropicProvider(
                api_key=settings.anthropic_api_key,
                default_model=settings.default_anthropic_model,
                base_url=settings.anthropic_api_base_url,
                api_version=settings.anthropic_api_version,
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

    async def generate_with_tools(
        self,
        *,
        provider: ProviderName,
        messages: list[Message],
        tools: list[ToolDefinition],
        tool_executor: Callable[[ToolCall], Awaitable[ToolResult]],
        model: str | None,
        system: str | None,
        timeout_seconds: int,
        max_turns: int = 10,
    ) -> ProviderResult:
        """Run a tool-calling loop: call LLM -> execute tools -> repeat until done."""
        adapter = self.providers[provider]
        current_messages = list(messages)

        for turn in range(max_turns):
            result = await adapter.generate_with_tools(
                messages=current_messages,
                tools=tools,
                model=model,
                system=system,
                timeout_seconds=timeout_seconds,
            )

            if not result.tool_calls:
                return result

            logger.info(
                "tool-calling turn %d: %d tool calls",
                turn + 1,
                len(result.tool_calls),
            )

            current_messages.append(Message(
                role="assistant",
                content=result.text if result.text else None,
                tool_calls=result.tool_calls,
            ))

            for tc in result.tool_calls:
                try:
                    tool_result = await tool_executor(tc)
                except Exception as exc:
                    logger.warning("tool %s failed: %s", tc.name, exc)
                    tool_result = ToolResult(
                        tool_call_id=tc.id,
                        content=f"Error: {exc}",
                        is_error=True,
                    )
                current_messages.append(Message(
                    role="tool",
                    tool_result=tool_result,
                ))

        return result

    async def generate_text_stream(
        self,
        *,
        provider: ProviderName,
        prompt: str,
        model: str | None,
        system: str | None,
        timeout_seconds: int,
    ) -> AsyncIterator[StreamDelta | StreamDone]:
        """Stream text from a provider. No retries -- yields deltas then done."""
        adapter = self.providers[provider]
        async for event in adapter.generate_text_stream(
            prompt=prompt,
            model=model,
            system=system,
            timeout_seconds=timeout_seconds,
        ):
            yield event
