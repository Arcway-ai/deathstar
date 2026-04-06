from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import pytest

from deathstar_server.services.memory_distiller import distill_memory


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
