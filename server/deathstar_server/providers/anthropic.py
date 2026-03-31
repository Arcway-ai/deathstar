from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from deathstar_server.providers.base import (
    BaseProvider,
    Message,
    ProviderResult,
    StreamDelta,
    StreamDone,
    ToolCall,
    ToolDefinition,
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

    async def generate_with_tools(
        self,
        *,
        messages: list[Message],
        tools: list[ToolDefinition],
        model: str | None,
        system: str | None,
        timeout_seconds: int,
    ) -> ProviderResult:
        api_key = self.require_api_key()
        selected_model = model or self.default_model

        # Build Anthropic messages from our Message objects
        anthropic_messages: list[dict[str, object]] = []
        for msg in messages:
            if msg.role == "user" and msg.content:
                anthropic_messages.append({"role": "user", "content": msg.content})
            elif msg.role == "assistant" and msg.content and not msg.tool_calls:
                anthropic_messages.append({"role": "assistant", "content": msg.content})
            elif msg.role == "assistant" and msg.tool_calls:
                content_blocks: list[dict[str, object]] = []
                if msg.content:
                    content_blocks.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments,
                    })
                anthropic_messages.append({"role": "assistant", "content": content_blocks})
            elif msg.role == "tool" and msg.tool_result:
                anthropic_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.tool_result.tool_call_id,
                        "content": msg.tool_result.content,
                        "is_error": msg.tool_result.is_error,
                    }],
                })

        # Convert tool definitions to Anthropic format
        anthropic_tools = [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters,
            }
            for t in tools
        ]

        payload: dict[str, object] = {
            "model": selected_model,
            "max_tokens": _max_tokens_for_model(selected_model),
            "messages": anthropic_messages,
            "tools": anthropic_tools,
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
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in data.get("content", []):
            if block.get("type") == "text" and block.get("text"):
                text_parts.append(str(block["text"]))
            elif block.get("type") == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.get("id", ""),
                    name=block.get("name", ""),
                    arguments=block.get("input", {}),
                ))

        text = "\n".join(text_parts) if text_parts else ""
        usage_payload = data.get("usage", {})
        input_tokens = usage_payload.get("input_tokens")
        output_tokens = usage_payload.get("output_tokens")
        total_tokens = None
        if input_tokens is not None and output_tokens is not None:
            total_tokens = int(input_tokens) + int(output_tokens)

        return ProviderResult(
            text=text,
            model=str(data.get("model", selected_model)),
            usage=UsageMetrics(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
            ),
            remote_response_id=data.get("id"),
            tool_calls=tool_calls if tool_calls else None,
        )

    async def generate_text_stream(
        self,
        *,
        prompt: str,
        model: str | None,
        system: str | None,
        timeout_seconds: int,
    ) -> AsyncIterator[StreamDelta | StreamDone]:
        api_key = self.require_api_key()
        selected_model = model or self.default_model

        payload: dict[str, object] = {
            "model": selected_model,
            "max_tokens": _max_tokens_for_model(selected_model),
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
        }
        if system:
            payload["system"] = system

        headers = {
            "x-api-key": api_key,
            "anthropic-version": self.api_version,
            "content-type": "application/json",
        }

        response_model = selected_model
        response_id: str | None = None
        input_tokens: int | None = None
        output_tokens: int | None = None

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds, connect=10)) as client:
                async with client.stream("POST", f"{self.base_url}/messages", json=payload, headers=headers) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        raise normalize_http_error(self.name, response)

                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = json.loads(line[6:])
                        event_type = data.get("type", "")

                        if event_type == "message_start":
                            msg = data.get("message", {})
                            response_model = str(msg.get("model", selected_model))
                            response_id = msg.get("id")
                            usage = msg.get("usage", {})
                            input_tokens = usage.get("input_tokens")
                        elif event_type == "content_block_delta":
                            delta = data.get("delta", {})
                            if delta.get("type") == "text_delta":
                                text = delta.get("text", "")
                                if text:
                                    yield StreamDelta(text=text)
                        elif event_type == "message_delta":
                            usage = data.get("usage", {})
                            output_tokens = usage.get("output_tokens")
                        elif event_type == "message_stop":
                            total = None
                            if input_tokens is not None and output_tokens is not None:
                                total = input_tokens + output_tokens
                            yield StreamDone(
                                model=response_model,
                                usage=UsageMetrics(
                                    input_tokens=input_tokens,
                                    output_tokens=output_tokens,
                                    total_tokens=total,
                                ),
                                remote_response_id=response_id,
                            )
        except httpx.HTTPError as exc:
            raise normalize_client_error(self.name, exc) from exc
