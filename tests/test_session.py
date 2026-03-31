from __future__ import annotations

import time

import pytest

from deathstar_server.session import (
    SESSION_COOKIE_NAME,
    cookie_params,
    generate_session_token,
    validate_session_token,
)


class TestGenerateAndValidate:
    def test_round_trip(self):
        token = generate_session_token("my-secret")
        assert validate_session_token(token, "my-secret")

    def test_different_secret_rejected(self):
        token = generate_session_token("secret-a")
        assert not validate_session_token(token, "secret-b")

    def test_expired_token(self):
        token = generate_session_token("s")
        # max_age=0 → immediately expired
        assert not validate_session_token(token, "s", max_age_seconds=0)

    def test_tampered_signature(self):
        token = generate_session_token("s")
        parts = token.split(":", 2)
        parts[2] = "0" * len(parts[2])  # overwrite signature
        assert not validate_session_token(":".join(parts), "s")

    def test_tampered_nonce(self):
        token = generate_session_token("s")
        parts = token.split(":", 2)
        parts[1] = "tampered"
        assert not validate_session_token(":".join(parts), "s")

    def test_malformed_token(self):
        assert not validate_session_token("garbage", "s")
        assert not validate_session_token("", "s")
        assert not validate_session_token("a:b", "s")  # only 2 parts

    def test_non_numeric_timestamp(self):
        assert not validate_session_token("abc:nonce:sig", "s")


class TestCookieParams:
    def test_secure_when_https(self):
        params = cookie_params(is_https=True)
        assert params["secure"] is True
        assert params["httponly"] is True
        assert params["samesite"] == "lax"
        assert params["key"] == SESSION_COOKIE_NAME

    def test_not_secure_when_http(self):
        params = cookie_params(is_https=False)
        assert params["secure"] is False


class TestCookieName:
    def test_name(self):
        assert SESSION_COOKIE_NAME == "ds_session"
