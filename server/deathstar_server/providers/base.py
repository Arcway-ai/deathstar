from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

from deathstar_server.errors import AppError
from deathstar_shared.models import ErrorCode, ProviderName, UsageMetrics


@dataclass(frozen=True)
class ProviderResult:
    text: str
    model: str
    usage: UsageMetrics | None = None
    remote_response_id: str | None = None


class BaseProvider(ABC):
    def __init__(self, *, api_key: str | None, default_model: str, base_url: str) -> None:
        self.api_key = api_key
        self.default_model = default_model
        self.base_url = base_url.rstrip("/")

    @property
    @abstractmethod
    def name(self) -> ProviderName:
        raise NotImplementedError

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def require_api_key(self) -> str:
        if not self.api_key:
            raise AppError(
                ErrorCode.PROVIDER_NOT_CONFIGURED,
                f"{self.name.value} is not configured on the remote runtime",
                status_code=400,
            )
        return self.api_key

    @abstractmethod
    async def generate_text(
        self,
        *,
        prompt: str,
        model: str | None,
        system: str | None,
        timeout_seconds: int,
    ) -> ProviderResult:
        raise NotImplementedError


def normalize_http_error(provider: ProviderName, response: httpx.Response) -> AppError:
    status_code = response.status_code
    message = _extract_error_message(response)

    if status_code in {401, 403}:
        return AppError(
            ErrorCode.AUTH_ERROR,
            f"{provider.value} authentication failed: {message}",
            status_code=status_code,
        )
    if status_code == 429:
        return AppError(
            ErrorCode.RATE_LIMITED,
            f"{provider.value} rate limited the request: {message}",
            status_code=status_code,
            retryable=True,
        )
    if status_code in {408, 504}:
        return AppError(
            ErrorCode.UPSTREAM_TIMEOUT,
            f"{provider.value} timed out: {message}",
            status_code=status_code,
            retryable=True,
        )
    if status_code >= 500:
        return AppError(
            ErrorCode.UPSTREAM_UNAVAILABLE,
            f"{provider.value} returned a server error: {message}",
            status_code=status_code,
            retryable=True,
        )
    return AppError(
        ErrorCode.INVALID_REQUEST,
        f"{provider.value} rejected the request: {message}",
        status_code=status_code,
    )


def normalize_client_error(provider: ProviderName, error: Exception) -> AppError:
    return AppError(
        ErrorCode.UPSTREAM_UNAVAILABLE,
        f"{provider.value} request failed: {error}",
        status_code=502,
        retryable=True,
    )


def ensure_text(text: str | None, provider: ProviderName) -> str:
    if text and text.strip():
        return text.strip()
    raise AppError(
        ErrorCode.INVALID_PROVIDER_OUTPUT,
        f"{provider.value} returned an empty or unsupported text payload",
        status_code=502,
    )


def _extract_error_message(response: httpx.Response, *, max_length: int = 200) -> str:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        raw = response.text.strip() or f"HTTP {response.status_code}"
        return raw[:max_length]

    if isinstance(payload, dict):
        if isinstance(payload.get("error"), dict):
            detail = payload["error"]
            msg = str(detail.get("message") or detail)
            return msg[:max_length]
        if "message" in payload:
            return str(payload["message"])[:max_length]
    return str(payload)[:max_length]


def as_usage(payload: dict[str, Any], *, input_key: str, output_key: str, total_key: str) -> UsageMetrics:
    return UsageMetrics(
        input_tokens=_to_int(payload.get(input_key)),
        output_tokens=_to_int(payload.get(output_key)),
        total_tokens=_to_int(payload.get(total_key)),
    )


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def extract_candidate_text(candidates: list[dict[str, Any]]) -> str | None:
    """Extract text from Gemini-style candidate response objects."""
    parts: list[str] = []
    for candidate in candidates:
        content = candidate.get("content", {})
        for part in content.get("parts", []):
            if part.get("text"):
                parts.append(str(part["text"]))
    return "\n".join(parts) if parts else None
