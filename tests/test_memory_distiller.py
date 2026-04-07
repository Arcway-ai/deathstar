from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import pytest

from deathstar_server.services.memory_distiller import distill_memory, suggest_memories


@pytest.mark.asyncio
async def test_distill_returns_content() -> None:
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="- Key learning: use async handlers")]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)

    with patch("deathstar_server.services.memory_distiller.anthropic.AsyncAnthropic", return_value=mock_client):
        result = await distill_memory(
            prompt="How do I handle async?",
            response="Here's a long explanation about async...",
            api_key="test-key",
        )
    assert result == "- Key learning: use async handlers"
    mock_client.messages.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_distill_falls_back_on_api_error() -> None:
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        side_effect=anthropic.APIConnectionError(request=MagicMock()),
    )

    with patch("deathstar_server.services.memory_distiller.anthropic.AsyncAnthropic", return_value=mock_client):
        result = await distill_memory(
            prompt="prompt",
            response="raw response content",
            api_key="test-key",
        )
    assert result == "raw response content"


@pytest.mark.asyncio
async def test_distill_falls_back_on_empty_content() -> None:
    mock_message = MagicMock()
    mock_message.content = []  # empty content list → IndexError

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)

    with patch("deathstar_server.services.memory_distiller.anthropic.AsyncAnthropic", return_value=mock_client):
        result = await distill_memory(
            prompt="prompt",
            response="raw response content",
            api_key="test-key",
        )
    assert result == "raw response content"


@pytest.mark.asyncio
async def test_distill_truncates_output() -> None:
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="x" * 5000)]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)

    with patch("deathstar_server.services.memory_distiller.anthropic.AsyncAnthropic", return_value=mock_client):
        result = await distill_memory(
            prompt="p",
            response="r",
            api_key="test-key",
        )
    assert len(result) == 2000


# ---------------------------------------------------------------------------
# suggest_memories tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suggest_returns_structured_suggestions() -> None:
    suggestions_json = json.dumps([
        {"content": "Always use frozen dataclasses for config objects.", "tags": ["convention", "pattern"]},
        {"content": "The auth middleware skips /health.", "tags": ["auth"]},
    ])
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=suggestions_json)]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)

    with patch("deathstar_server.services.memory_distiller.anthropic.AsyncAnthropic", return_value=mock_client):
        result = await suggest_memories(
            messages=[
                {"role": "user", "content": "How should config work?"},
                {"role": "assistant", "content": "Use frozen dataclasses..."},
            ],
            api_key="test-key",
        )
    assert len(result) == 2
    assert result[0].content == "Always use frozen dataclasses for config objects."
    assert result[0].tags == ["convention", "pattern"]
    assert result[1].content == "The auth middleware skips /health."
    mock_client.messages.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_suggest_handles_markdown_fenced_json() -> None:
    fenced = '```json\n[{"content": "tip", "tags": ["misc"]}]\n```'
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=fenced)]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)

    with patch("deathstar_server.services.memory_distiller.anthropic.AsyncAnthropic", return_value=mock_client):
        result = await suggest_memories(
            messages=[{"role": "user", "content": "test"}],
            api_key="test-key",
        )
    assert len(result) == 1
    assert result[0].content == "tip"


@pytest.mark.asyncio
async def test_suggest_returns_empty_on_api_error() -> None:
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        side_effect=anthropic.APIConnectionError(request=MagicMock()),
    )

    with patch("deathstar_server.services.memory_distiller.anthropic.AsyncAnthropic", return_value=mock_client):
        result = await suggest_memories(
            messages=[{"role": "user", "content": "test"}],
            api_key="test-key",
        )
    assert result == []


@pytest.mark.asyncio
async def test_suggest_returns_empty_on_invalid_json() -> None:
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="this is not json")]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)

    with patch("deathstar_server.services.memory_distiller.anthropic.AsyncAnthropic", return_value=mock_client):
        result = await suggest_memories(
            messages=[{"role": "user", "content": "test"}],
            api_key="test-key",
        )
    assert result == []


@pytest.mark.asyncio
async def test_suggest_returns_empty_for_empty_messages() -> None:
    result = await suggest_memories(messages=[], api_key="test-key")
    assert result == []


@pytest.mark.asyncio
async def test_suggest_caps_at_eight_items() -> None:
    items = [{"content": f"item {i}", "tags": []} for i in range(12)]
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=json.dumps(items))]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)

    with patch("deathstar_server.services.memory_distiller.anthropic.AsyncAnthropic", return_value=mock_client):
        result = await suggest_memories(
            messages=[{"role": "user", "content": "test"}],
            api_key="test-key",
        )
    assert len(result) == 8


@pytest.mark.asyncio
async def test_suggest_skips_items_with_empty_content() -> None:
    items = [
        {"content": "valid", "tags": ["ok"]},
        {"content": "", "tags": []},
        {"content": "  ", "tags": []},
        {"content": "also valid", "tags": ["ok"]},
    ]
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=json.dumps(items))]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)

    with patch("deathstar_server.services.memory_distiller.anthropic.AsyncAnthropic", return_value=mock_client):
        result = await suggest_memories(
            messages=[{"role": "user", "content": "test"}],
            api_key="test-key",
        )
    assert len(result) == 2
    assert result[0].content == "valid"
    assert result[1].content == "also valid"
