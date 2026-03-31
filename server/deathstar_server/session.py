"""Signed session cookie utilities for web UI authentication.

The web UI uses HttpOnly session cookies instead of bearer tokens.
Cookies are HMAC-SHA256 signed using the API token as the key.
CLI endpoints continue to use bearer token auth.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time

SESSION_COOKIE_NAME = "ds_session"
_MAX_AGE_SECONDS = 7 * 24 * 60 * 60  # 7 days


def generate_session_token(secret: str) -> str:
    """Generate a signed session token: ``timestamp:nonce:signature``."""
    timestamp = str(int(time.time()))
    nonce = secrets.token_urlsafe(32)
    signature = hmac.new(
        secret.encode(), f"{timestamp}:{nonce}".encode(), hashlib.sha256
    ).hexdigest()
    return f"{timestamp}:{nonce}:{signature}"


def validate_session_token(
    token: str, secret: str, max_age_seconds: int = _MAX_AGE_SECONDS
) -> bool:
    """Validate a signed session token.  Returns ``False`` for expired or tampered tokens."""
    try:
        parts = token.split(":", 2)
        if len(parts) != 3:
            return False
        timestamp_str, nonce, signature = parts
        timestamp = int(timestamp_str)
    except (ValueError, AttributeError):
        return False

    # Check expiry
    if time.time() - timestamp > max_age_seconds:
        return False

    # Recompute and compare
    expected = hmac.new(
        secret.encode(), f"{timestamp_str}:{nonce}".encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


def cookie_params(*, is_https: bool) -> dict:
    """Return kwargs for ``response.set_cookie()``."""
    return {
        "key": SESSION_COOKIE_NAME,
        "httponly": True,
        "samesite": "lax",
        "secure": is_https,
        "path": "/",
        "max_age": _MAX_AGE_SECONDS,
    }
