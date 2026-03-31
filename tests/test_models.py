from __future__ import annotations

import pytest
from pydantic import ValidationError

from deathstar_shared.models import (
    ErrorCode,
    ErrorEnvelope,
    ProviderName,
    StatusResponse,
    UsageMetrics,
    WorkflowKind,
    WorkflowRequest,
    WorkflowResponse,
)


# ---------------------------------------------------------------------------
# WorkflowRequest validation
# ---------------------------------------------------------------------------

class TestWorkflowRequestValidation:
    def test_valid_minimal_request(self):
        req = WorkflowRequest(provider=ProviderName.ANTHROPIC, prompt="Hello")
        assert req.workflow == WorkflowKind.PROMPT
        assert req.workspace_subpath == "."
        assert req.timeout_seconds == 180

    def test_valid_full_request(self):
        req = WorkflowRequest(
            workflow=WorkflowKind.PATCH,
            provider=ProviderName.ANTHROPIC,
            prompt="Fix the bug",
            workspace_subpath="myrepo/src",
            model="claude-sonnet-4-5-20250514",
            system="be concise",
            timeout_seconds=300,
            write_changes=True,
        )
        assert req.workspace_subpath == "myrepo/src"

    def test_prompt_min_length(self):
        with pytest.raises(ValidationError) as exc_info:
            WorkflowRequest(provider=ProviderName.ANTHROPIC, prompt="")
        errors = exc_info.value.errors()
        assert any(e["type"] == "string_too_short" for e in errors)

    def test_prompt_max_length(self):
        with pytest.raises(ValidationError) as exc_info:
            WorkflowRequest(provider=ProviderName.ANTHROPIC, prompt="x" * 200_001)
        errors = exc_info.value.errors()
        assert any(e["type"] == "string_too_long" for e in errors)

    def test_workspace_subpath_rejects_parent_traversal(self):
        with pytest.raises(ValidationError) as exc_info:
            WorkflowRequest(
                provider=ProviderName.ANTHROPIC,
                prompt="test",
                workspace_subpath="../secret",
            )
        # Should be caught by the field_validator
        assert exc_info.value.error_count() >= 1

    def test_workspace_subpath_rejects_double_dot(self):
        with pytest.raises(ValidationError):
            WorkflowRequest(
                provider=ProviderName.ANTHROPIC,
                prompt="test",
                workspace_subpath="..",
            )

    def test_workspace_subpath_rejects_embedded_traversal(self):
        with pytest.raises(ValidationError):
            WorkflowRequest(
                provider=ProviderName.ANTHROPIC,
                prompt="test",
                workspace_subpath="foo/../bar",
            )

    def test_workspace_subpath_rejects_absolute_path(self):
        with pytest.raises(ValidationError):
            WorkflowRequest(
                provider=ProviderName.ANTHROPIC,
                prompt="test",
                workspace_subpath="/etc/passwd",
            )

    def test_workspace_subpath_accepts_dot(self):
        req = WorkflowRequest(
            provider=ProviderName.ANTHROPIC,
            prompt="test",
            workspace_subpath=".",
        )
        assert req.workspace_subpath == "."

    def test_workspace_subpath_accepts_nested_path(self):
        req = WorkflowRequest(
            provider=ProviderName.ANTHROPIC,
            prompt="test",
            workspace_subpath="project/src/main",
        )
        assert req.workspace_subpath == "project/src/main"

    def test_workspace_subpath_accepts_hyphens_underscores(self):
        req = WorkflowRequest(
            provider=ProviderName.ANTHROPIC,
            prompt="test",
            workspace_subpath="my-project_v2",
        )
        assert req.workspace_subpath == "my-project_v2"

    def test_timeout_seconds_min(self):
        with pytest.raises(ValidationError):
            WorkflowRequest(
                provider=ProviderName.ANTHROPIC,
                prompt="test",
                timeout_seconds=4,
            )

    def test_timeout_seconds_max(self):
        with pytest.raises(ValidationError):
            WorkflowRequest(
                provider=ProviderName.ANTHROPIC,
                prompt="test",
                timeout_seconds=901,
            )

    def test_timeout_seconds_valid_bounds(self):
        req_min = WorkflowRequest(provider=ProviderName.ANTHROPIC, prompt="x", timeout_seconds=5)
        assert req_min.timeout_seconds == 5

        req_max = WorkflowRequest(provider=ProviderName.ANTHROPIC, prompt="x", timeout_seconds=900)
        assert req_max.timeout_seconds == 900


# ---------------------------------------------------------------------------
# WorkflowResponse serialization
# ---------------------------------------------------------------------------

class TestWorkflowResponseSerialization:
    def test_successful_response(self):
        resp = WorkflowResponse(
            request_id="abc-123",
            workflow=WorkflowKind.PROMPT,
            status="succeeded",
            provider=ProviderName.ANTHROPIC,
            model="claude-sonnet-4-5-20250514",
            content="Hello!",
            workspace_subpath=".",
            duration_ms=150,
            usage=UsageMetrics(input_tokens=10, output_tokens=5, total_tokens=15),
        )
        data = resp.model_dump(mode="json")
        assert data["status"] == "succeeded"
        assert data["content"] == "Hello!"
        assert data["usage"]["total_tokens"] == 15
        assert data["error"] is None

    def test_failed_response(self):
        resp = WorkflowResponse(
            request_id="abc-456",
            workflow=WorkflowKind.PATCH,
            status="failed",
            provider=ProviderName.ANTHROPIC,
            model="claude-sonnet-4-5-20250514",
            workspace_subpath="myrepo",
            duration_ms=50,
            error=ErrorEnvelope(
                code=ErrorCode.AUTH_ERROR,
                message="bad key",
                retryable=False,
            ),
        )
        data = resp.model_dump(mode="json")
        assert data["status"] == "failed"
        assert data["error"]["code"] == "auth_error"
        assert data["content"] is None

    def test_artifacts_default_empty(self):
        resp = WorkflowResponse(
            request_id="x",
            workflow=WorkflowKind.PROMPT,
            status="succeeded",
            provider=ProviderName.ANTHROPIC,
            model="m",
            workspace_subpath=".",
            duration_ms=0,
        )
        assert resp.artifacts == {}


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
