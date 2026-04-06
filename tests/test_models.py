from __future__ import annotations

from deathstar_shared.models import (
    ErrorCode,
    ErrorEnvelope,
    StatusResponse,
    UsageMetrics,
    WorkflowKind,
)


# ---------------------------------------------------------------------------
# StatusResponse serialization
# ---------------------------------------------------------------------------

class TestStatusResponseSerialization:
    def test_serialization(self):
        resp = StatusResponse(
            service="healthy",
            version="0.1.0",
            workspace_root="/workspace",
            projects_root="/workspace/projects",
            log_path="/workspace/logs/api.log",
            backup_directory="/workspace/backups",
            backup_bucket="my-bucket",
            github_prs_enabled=True,
            providers={
                "anthropic": {"configured": True, "default_model": "claude-sonnet-4-5-20250514"},
            },
            workflows=[WorkflowKind.PROMPT, WorkflowKind.PATCH],
        )
        data = resp.model_dump(mode="json")
        assert data["service"] == "healthy"
        assert data["providers"]["anthropic"]["configured"] is True
        assert data["backup_bucket"] == "my-bucket"

    def test_defaults(self):
        resp = StatusResponse(
            service="healthy",
            version="0.1.0",
            workspace_root="/w",
            projects_root="/p",
            log_path="/l",
            backup_directory="/b",
            providers={},
            workflows=[],
        )
        assert resp.backup_bucket is None
        assert resp.github_prs_enabled is False
        assert resp.preferred_transport == "ssm"
        assert resp.tailscale_enabled is False
        assert resp.ssh_user == "ubuntu"


# ---------------------------------------------------------------------------
# ErrorEnvelope
# ---------------------------------------------------------------------------

class TestErrorEnvelope:
    def test_creation(self):
        env = ErrorEnvelope(
            code=ErrorCode.RATE_LIMITED,
            message="slow down",
            retryable=True,
        )
        assert env.code == ErrorCode.RATE_LIMITED
        assert env.message == "slow down"
        assert env.retryable is True
        assert env.details == {}

    def test_with_details(self):
        env = ErrorEnvelope(
            code=ErrorCode.INTERNAL_ERROR,
            message="boom",
            details={"trace_id": "abc"},
        )
        data = env.model_dump(mode="json")
        assert data["details"]["trace_id"] == "abc"

    def test_default_retryable_false(self):
        env = ErrorEnvelope(code=ErrorCode.AUTH_ERROR, message="denied")
        assert env.retryable is False

    def test_serialization_uses_enum_values(self):
        env = ErrorEnvelope(code=ErrorCode.UPSTREAM_TIMEOUT, message="timeout")
        data = env.model_dump(mode="json")
        assert data["code"] == "upstream_timeout"


# ---------------------------------------------------------------------------
# UsageMetrics
# ---------------------------------------------------------------------------

class TestUsageMetrics:
    def test_all_none(self):
        u = UsageMetrics()
        assert u.input_tokens is None
        assert u.output_tokens is None
        assert u.total_tokens is None

    def test_partial_values(self):
        u = UsageMetrics(input_tokens=10)
        assert u.input_tokens == 10
        assert u.output_tokens is None
