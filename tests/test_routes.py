from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deathstar_shared.models import (
    ErrorCode,
    ProviderName,
    ProviderStatus,
    UsageMetrics,
    WorkflowKind,
    WorkflowResponse,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_workflow_response() -> WorkflowResponse:
    return WorkflowResponse(
        request_id="test-id",
        workflow=WorkflowKind.PROMPT,
        status="succeeded",
        provider=ProviderName.OPENAI,
        model="gpt-4o-mini",
        content="Hello!",
        workspace_subpath=".",
        duration_ms=100,
        usage=UsageMetrics(input_tokens=10, output_tokens=5, total_tokens=15),
    )


def _make_provider_status() -> dict[str, ProviderStatus]:
    return {
        "openai": ProviderStatus(configured=True, default_model="gpt-4o-mini"),
        "anthropic": ProviderStatus(configured=True, default_model="claude-sonnet-4-5-20250514"),
        "google": ProviderStatus(configured=True, default_model="gemini-2.0-flash"),
    }


def _build_app(tmp_path: Path, api_token: str | None = None):
    """Build a fresh FastAPI app with mocked app_state to avoid module-level side effects."""
    mock_settings = MagicMock()
    mock_settings.api_token = api_token
    mock_settings.workspace_root = tmp_path
    mock_settings.projects_root = tmp_path / "projects"
    mock_settings.log_path = tmp_path / "log.txt"
    mock_settings.backup_directory = tmp_path / "backups"
    mock_settings.backup_bucket = None
    mock_settings.github_token = "ghp-test"
    mock_settings.tailscale_enabled = False
    mock_settings.tailscale_hostname = None
    mock_settings.ssh_user = "ec2-user"

    mock_workflow = MagicMock()
    mock_workflow.execute = AsyncMock(return_value=_make_workflow_response())
    mock_workflow.providers = MagicMock()
    mock_workflow.providers.status.return_value = _make_provider_status()

    mock_backup = MagicMock()
    mock_backup.latest_log_lines.return_value = ["line1", "line2"]

    # Create a mock module for app_state
    mock_app_state = MagicMock()
    mock_app_state.settings = mock_settings
    mock_app_state.workflow_service = mock_workflow
    mock_app_state.backup_service = mock_backup

    # Inject mock before importing app/routes
    saved_modules = {}
    for mod_name in list(sys.modules):
        if mod_name.startswith("deathstar_server.app") or mod_name.startswith("deathstar_server.routes"):
            saved_modules[mod_name] = sys.modules.pop(mod_name)

    sys.modules["deathstar_server.app_state"] = mock_app_state

    try:
        import importlib

        if "deathstar_server.routes" in sys.modules:
            importlib.reload(sys.modules["deathstar_server.routes"])
        else:
            import deathstar_server.routes  # noqa: F811

        if "deathstar_server.app" in sys.modules:
            importlib.reload(sys.modules["deathstar_server.app"])
        else:
            import deathstar_server.app  # noqa: F811

        from deathstar_server.app import app
        from fastapi.testclient import TestClient

        return TestClient(app), mock_workflow, mock_backup
    finally:
        pass  # Keep the mocked modules active for the test


@pytest.fixture
def client_no_auth(tmp_path):
    """TestClient with no API token configured."""
    client, _, _ = _build_app(tmp_path, api_token=None)
    yield client


@pytest.fixture
def client_with_auth(tmp_path):
    """TestClient with API token configured."""
    client, _, _ = _build_app(tmp_path, api_token="secret-token")
    yield client


# ---------------------------------------------------------------------------
# GET /v1/health
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_returns_ok(self, client_no_auth):
        response = client_no_auth.get("/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_health_accessible_without_token(self, client_with_auth):
        response = client_with_auth.get("/v1/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# GET /v1/status
# ---------------------------------------------------------------------------

class TestStatusEndpoint:
    def test_returns_status(self, client_no_auth):
        response = client_no_auth.get("/v1/status")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "healthy"
        assert "providers" in data
        assert "workflows" in data


# ---------------------------------------------------------------------------
# POST /v1/run
# ---------------------------------------------------------------------------

class TestRunEndpoint:
    def test_executes_workflow(self, client_no_auth):
        response = client_no_auth.post(
            "/v1/run",
            json={
                "provider": "openai",
                "prompt": "Hello",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "succeeded"
        assert data["content"] == "Hello!"

    def test_rejects_invalid_request(self, client_no_auth):
        response = client_no_auth.post(
            "/v1/run",
            json={
                "provider": "openai",
                "prompt": "",  # too short
            },
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /v1/logs
# ---------------------------------------------------------------------------

class TestLogsEndpoint:
    def test_returns_logs(self, client_no_auth):
        response = client_no_auth.get("/v1/logs")
        assert response.status_code == 200
        data = response.json()
        assert "lines" in data

    def test_rejects_tail_over_10000(self, client_no_auth):
        response = client_no_auth.get("/v1/logs?tail=10001")
        assert response.status_code == 422

    def test_rejects_tail_under_1(self, client_no_auth):
        response = client_no_auth.get("/v1/logs?tail=0")
        assert response.status_code == 422

    def test_valid_tail_param(self, client_no_auth):
        response = client_no_auth.get("/v1/logs?tail=50")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------

class TestAuthMiddleware:
    def test_rejects_when_token_missing(self, client_with_auth):
        response = client_with_auth.get("/v1/status")
        assert response.status_code == 401
        data = response.json()
        assert data["code"] == "auth_error"

    def test_rejects_wrong_token(self, client_with_auth):
        response = client_with_auth.get(
            "/v1/status",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert response.status_code == 401

    def test_allows_correct_token(self, client_with_auth):
        response = client_with_auth.get(
            "/v1/status",
            headers={"Authorization": "Bearer secret-token"},
        )
        assert response.status_code == 200

    def test_allows_health_without_token(self, client_with_auth):
        response = client_with_auth.get("/v1/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_run_requires_token(self, client_with_auth):
        response = client_with_auth.post(
            "/v1/run",
            json={"provider": "openai", "prompt": "test"},
        )
        assert response.status_code == 401

    def test_run_with_correct_token(self, client_with_auth):
        response = client_with_auth.post(
            "/v1/run",
            json={"provider": "openai", "prompt": "test"},
            headers={"Authorization": "Bearer secret-token"},
        )
        assert response.status_code == 200
