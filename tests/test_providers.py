from __future__ import annotations

import json
from unittest.mock import AsyncMock

import httpx
import pytest

from deathstar_server.errors import AppError
from deathstar_server.providers.anthropic import AnthropicProvider
from deathstar_server.providers.base import (
    ProviderResult,
    as_usage,
    ensure_text,
    normalize_client_error,
    normalize_http_error,
)
from deathstar_shared.models import ErrorCode, ProviderName, UsageMetrics


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(status_code: int, json_body: dict | None = None, text: str = "") -> httpx.Response:
    """Build a minimal httpx.Response for testing."""
    if json_body is not None:
        content = json.dumps(json_body).encode()
        headers = {"content-type": "application/json"}
    else:
        content = text.encode()
        headers = {"content-type": "text/plain"}

    return httpx.Response(
        status_code=status_code,
        content=content,
        headers=headers,
        request=httpx.Request("POST", "https://example.com"),
    )


# ---------------------------------------------------------------------------
# Base helpers: normalize_http_error
# ---------------------------------------------------------------------------

class TestNormalizeHttpError:
    def test_auth_error_401(self):
        resp = _mock_response(401, {"error": {"message": "bad key"}})
        err = normalize_http_error(ProviderName.ANTHROPIC, resp)
        assert isinstance(err, AppError)
        assert err.code == ErrorCode.AUTH_ERROR
        assert err.status_code == 401
        assert "bad key" in err.message

    def test_auth_error_403(self):
        resp = _mock_response(403, {"message": "forbidden"})
        err = normalize_http_error(ProviderName.ANTHROPIC, resp)
        assert err.code == ErrorCode.AUTH_ERROR
        assert err.status_code == 403

    def test_rate_limited_429(self):
        resp = _mock_response(429, {"error": {"message": "slow down"}})
        err = normalize_http_error(ProviderName.ANTHROPIC, resp)
        assert err.code == ErrorCode.RATE_LIMITED
        assert err.retryable is True

    def test_upstream_timeout_504(self):
        resp = _mock_response(504, {"message": "gateway timeout"})
        err = normalize_http_error(ProviderName.ANTHROPIC, resp)
        assert err.code == ErrorCode.UPSTREAM_TIMEOUT
        assert err.retryable is True

    def test_server_error_500(self):
        resp = _mock_response(500, {"error": {"message": "internal"}})
        err = normalize_http_error(ProviderName.ANTHROPIC, resp)
        assert err.code == ErrorCode.UPSTREAM_UNAVAILABLE
        assert err.retryable is True

    def test_client_error_422(self):
        resp = _mock_response(422, {"error": {"message": "bad payload"}})
        err = normalize_http_error(ProviderName.ANTHROPIC, resp)
        assert err.code == ErrorCode.INVALID_REQUEST
        assert err.retryable is False

    def test_plain_text_error_body(self):
        resp = _mock_response(500, text="oops")
        err = normalize_http_error(ProviderName.ANTHROPIC, resp)
        assert "oops" in err.message


class TestNormalizeClientError:
    def test_wraps_exception(self):
        exc = httpx.ConnectError("refused")
        err = normalize_client_error(ProviderName.ANTHROPIC, exc)
        assert err.code == ErrorCode.UPSTREAM_UNAVAILABLE
        assert err.status_code == 502
        assert err.retryable is True
        assert "refused" in err.message


class TestEnsureText:
    def test_returns_stripped_text(self):
        assert ensure_text("  hello  ", ProviderName.ANTHROPIC) == "hello"

    def test_raises_on_empty(self):
        with pytest.raises(AppError) as exc_info:
            ensure_text("", ProviderName.ANTHROPIC)
        assert exc_info.value.code == ErrorCode.INVALID_PROVIDER_OUTPUT

    def test_raises_on_whitespace_only(self):
        with pytest.raises(AppError):
            ensure_text("   ", ProviderName.ANTHROPIC)

    def test_raises_on_none(self):
        with pytest.raises(AppError):
            ensure_text(None, ProviderName.ANTHROPIC)


class TestAsUsage:
    def test_parses_all_fields(self):
        payload = {"in": 100, "out": 200, "tot": 300}
        usage = as_usage(payload, input_key="in", output_key="out", total_key="tot")
        assert usage.input_tokens == 100
        assert usage.output_tokens == 200
        assert usage.total_tokens == 300

    def test_missing_keys_return_none(self):
        usage = as_usage({}, input_key="in", output_key="out", total_key="tot")
        assert usage.input_tokens is None
        assert usage.output_tokens is None
        assert usage.total_tokens is None

    def test_non_numeric_values_return_none(self):
        payload = {"in": "not-a-number", "out": None, "tot": []}
        usage = as_usage(payload, input_key="in", output_key="out", total_key="tot")
        assert usage.input_tokens is None
        assert usage.output_tokens is None
        assert usage.total_tokens is None


# ---------------------------------------------------------------------------
# Anthropic Provider
# ---------------------------------------------------------------------------

class TestAnthropicProvider:
    def _make_provider(self, api_key: str | None = "sk-test") -> AnthropicProvider:
        return AnthropicProvider(
            api_key=api_key,
            default_model="claude-sonnet-4-5-20250514",
            base_url="https://api.anthropic.com/v1",
            api_version="2023-06-01",
        )

    @pytest.mark.asyncio
    async def test_successful_generation(self, monkeypatch):
        provider = self._make_provider()
        response_json = {
            "id": "msg-123",
            "content": [{"type": "text", "text": "Greetings!"}],
            "model": "claude-sonnet-4-5-20250514",
            "usage": {"input_tokens": 8, "output_tokens": 3},
        }

        async def mock_post(self_client, url, **kwargs):
            return _mock_response(200, response_json)

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

        result = await provider.generate_text(prompt="hi", model=None, system=None, timeout_seconds=30)
        assert result.text == "Greetings!"
        assert result.model == "claude-sonnet-4-5-20250514"
        assert result.usage.input_tokens == 8
        assert result.usage.output_tokens == 3
        assert result.usage.total_tokens == 11
        assert result.remote_response_id == "msg-123"

    @pytest.mark.asyncio
    async def test_system_prompt_included(self, monkeypatch):
        provider = self._make_provider()
        captured = {}

        async def mock_post(self_client, url, **kwargs):
            captured["payload"] = kwargs.get("json", {})
            return _mock_response(200, {
                "content": [{"type": "text", "text": "ok"}],
                "model": "claude-sonnet-4-5-20250514",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            })

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

        await provider.generate_text(prompt="test", model=None, system="be concise", timeout_seconds=30)
        assert captured["payload"]["system"] == "be concise"

    @pytest.mark.asyncio
    async def test_api_version_header(self, monkeypatch):
        provider = self._make_provider()
        captured = {}

        async def mock_post(self_client, url, **kwargs):
            captured["headers"] = kwargs.get("headers", {})
            return _mock_response(200, {
                "content": [{"type": "text", "text": "ok"}],
                "model": "claude-sonnet-4-5-20250514",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            })

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

        await provider.generate_text(prompt="test", model=None, system=None, timeout_seconds=30)
        assert captured["headers"]["anthropic-version"] == "2023-06-01"

    @pytest.mark.asyncio
    async def test_http_error_401(self, monkeypatch):
        provider = self._make_provider()

        async def mock_post(self_client, url, **kwargs):
            return _mock_response(401, {"error": {"message": "unauthorized"}})

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

        with pytest.raises(AppError) as exc_info:
            await provider.generate_text(prompt="hi", model=None, system=None, timeout_seconds=30)
        assert exc_info.value.code == ErrorCode.AUTH_ERROR

    @pytest.mark.asyncio
    async def test_connection_error(self, monkeypatch):
        provider = self._make_provider()

        async def mock_post(self_client, url, **kwargs):
            raise httpx.ConnectError("timeout")

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

        with pytest.raises(AppError) as exc_info:
            await provider.generate_text(prompt="hi", model=None, system=None, timeout_seconds=30)
        assert exc_info.value.code == ErrorCode.UPSTREAM_UNAVAILABLE

    @pytest.mark.asyncio
    async def test_missing_api_key(self):
        provider = self._make_provider(api_key=None)
        with pytest.raises(AppError) as exc_info:
            await provider.generate_text(prompt="hi", model=None, system=None, timeout_seconds=30)
        assert exc_info.value.code == ErrorCode.PROVIDER_NOT_CONFIGURED

    @pytest.mark.asyncio
    async def test_empty_response_text(self, monkeypatch):
        provider = self._make_provider()

        async def mock_post(self_client, url, **kwargs):
            return _mock_response(200, {
                "content": [],
                "model": "claude-sonnet-4-5-20250514",
                "usage": {"input_tokens": 1, "output_tokens": 0},
            })

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

        with pytest.raises(AppError) as exc_info:
            await provider.generate_text(prompt="hi", model=None, system=None, timeout_seconds=30)
        assert exc_info.value.code == ErrorCode.INVALID_PROVIDER_OUTPUT


# ---------------------------------------------------------------------------
# Provider property tests
# ---------------------------------------------------------------------------

class TestProviderProperties:
    def test_anthropic_name(self):
        p = AnthropicProvider(api_key="k", default_model="m", base_url="http://x", api_version="v")
        assert p.name == ProviderName.ANTHROPIC

    def test_configured_true(self):
        p = AnthropicProvider(api_key="sk-abc", default_model="m", base_url="http://x", api_version="v")
        assert p.configured is True

    def test_configured_false(self):
        p = AnthropicProvider(api_key=None, default_model="m", base_url="http://x", api_version="v")
        assert p.configured is False

    def test_configured_false_empty_string(self):
        p = AnthropicProvider(api_key="", default_model="m", base_url="http://x", api_version="v")
        assert p.configured is False

    def test_base_url_strips_trailing_slash(self):
        p = AnthropicProvider(api_key="k", default_model="m", base_url="http://x/v1/", api_version="v")
        assert p.base_url == "http://x/v1"
