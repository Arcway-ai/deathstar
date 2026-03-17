from __future__ import annotations

from typing import Any

from deathstar_shared.models import ErrorCode, ErrorEnvelope


class AppError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        status_code: int = 400,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.details = details or {}

    def to_envelope(self) -> ErrorEnvelope:
        return ErrorEnvelope(
            code=self.code,
            message=self.message,
            retryable=self.retryable,
            details=self.details,
        )
