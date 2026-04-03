"""Tests for the WebSocket agent endpoint, session management, and agent runner."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from deathstar_shared.models import WorkflowKind


# ---------------------------------------------------------------------------
# Helpers — avoid importing agent_ws/agent_runner at module level (they need app_state)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_app_state():
    """Provide a mock app_state so agent_ws and agent_runner can import."""
    mock = MagicMock()
    mock.settings.api_token = None
    mock.settings.workspace_root = Path("/tmp/test-ws")
    mock.settings.projects_root = Path("/tmp/test-ws/projects")
    saved = sys.modules.get("deathstar_server.app_state")
    sys.modules["deathstar_server.app_state"] = mock
    yield mock
    if saved is not None:
        sys.modules["deathstar_server.app_state"] = saved
    else:
        sys.modules.pop("deathstar_server.app_state", None)
    # Clear cached imports for modules we force-reimport in tests.
    # Be specific to avoid poisoning unrelated test modules.
    for mod_name in list(sys.modules):
        if mod_name.startswith("deathstar_server.web.agent_ws") or \
           mod_name.startswith("deathstar_server.services.agent_runner") or \
           mod_name == "deathstar_server.services.agent":
            sys.modules.pop(mod_name, None)


def _import_agent_ws():
    # Force re-import with mocked app_state
    sys.modules.pop("deathstar_server.web.agent_ws", None)
    sys.modules.pop("deathstar_server.services.agent", None)
    sys.modules.pop("deathstar_server.services.agent_runner", None)
    from deathstar_server.web import agent_ws
    return agent_ws


def _import_agent_runner():
    sys.modules.pop("deathstar_server.services.agent_runner", None)
    sys.modules.pop("deathstar_server.services.agent", None)
    from deathstar_server.services import agent_runner
    return agent_runner


# ---------------------------------------------------------------------------
# _build_options (now in agent_runner)
# ---------------------------------------------------------------------------


class TestBuildOptions:
    def test_includes_partial_messages(self):
        mod = _import_agent_runner()
        opts = mod._build_options(workflow=WorkflowKind.PROMPT, cwd="/tmp/repo")
        assert opts.include_partial_messages is True

    def test_can_use_tool_injected(self):
        mod = _import_agent_runner()

        async def my_callback(name, inp, ctx):
            pass

        opts = mod._build_options(
            workflow=WorkflowKind.PROMPT, cwd="/tmp/repo", can_use_tool=my_callback,
        )
        assert opts.can_use_tool is my_callback

    def test_session_resume(self):
        mod = _import_agent_runner()
        opts = mod._build_options(
            workflow=WorkflowKind.PROMPT, cwd="/tmp", session_id="sess-123",
        )
        assert opts.resume == "sess-123"


# ---------------------------------------------------------------------------
# _usage_dict (now in agent_runner)
# ---------------------------------------------------------------------------


class TestUsageDict:
    def test_dict_input(self):
        mod = _import_agent_runner()
        result = mod._usage_dict({"input_tokens": 100, "output_tokens": 50})
        assert result == {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}

    def test_none_input(self):
        mod = _import_agent_runner()
        assert mod._usage_dict(None) is None

    def test_missing_keys(self):
        mod = _import_agent_runner()
        result = mod._usage_dict({})
        assert result == {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


# ---------------------------------------------------------------------------
# _authenticate (still in agent_ws)
# ---------------------------------------------------------------------------


def _mock_websocket(*, cookies=None, query_params=None):
    ws = MagicMock()
    ws.cookies = cookies or {}
    ws.query_params = query_params or {}
    return ws


class TestAuthenticate:
    def test_no_token_configured_allows_all(self, _mock_app_state):
        mod = _import_agent_ws()
        _mock_app_state.settings.api_token = None
        ws = _mock_websocket()
        assert mod._authenticate(ws) is True

    def test_rejects_missing_token(self, _mock_app_state):
        mod = _import_agent_ws()
        _mock_app_state.settings.api_token = "secret"
        ws = _mock_websocket()
        assert mod._authenticate(ws) is False

    def test_rejects_wrong_token(self, _mock_app_state):
        mod = _import_agent_ws()
        _mock_app_state.settings.api_token = "secret"
        ws = _mock_websocket(query_params={"token": "wrong"})
        assert mod._authenticate(ws) is False

    def test_accepts_correct_cookie(self, _mock_app_state):
        from deathstar_server.session import SESSION_COOKIE_NAME, generate_session_token
        mod = _import_agent_ws()
        _mock_app_state.settings.api_token = "secret"
        cookie = generate_session_token("secret")
        ws = _mock_websocket(cookies={SESSION_COOKIE_NAME: cookie})
        assert mod._authenticate(ws) is True

    def test_accepts_legacy_query_token(self, _mock_app_state):
        mod = _import_agent_ws()
        _mock_app_state.settings.api_token = "secret"
        ws = _mock_websocket(query_params={"token": "secret"})
        assert mod._authenticate(ws) is True

    def test_rejects_bad_cookie(self, _mock_app_state):
        from deathstar_server.session import SESSION_COOKIE_NAME
        mod = _import_agent_ws()
        _mock_app_state.settings.api_token = "secret"
        ws = _mock_websocket(cookies={SESSION_COOKIE_NAME: "garbage"})
        assert mod._authenticate(ws) is False


# ---------------------------------------------------------------------------
# _check_protected_branch_push (now in agent_runner)
# ---------------------------------------------------------------------------


class TestProtectedBranchPush:
    def test_blocks_push_to_main(self):
        mod = _import_agent_runner()
        result = mod._check_protected_branch_push("Bash", {"command": "git push origin main"})
        assert result is not None
        assert "main" in result.message.lower() or "not allowed" in result.message.lower()

    def test_blocks_push_to_master(self):
        mod = _import_agent_runner()
        result = mod._check_protected_branch_push("Bash", {"command": "git push origin master"})
        assert result is not None

    def test_blocks_bare_push(self):
        mod = _import_agent_runner()
        result = mod._check_protected_branch_push("Bash", {"command": "git push"})
        assert result is not None

    def test_blocks_bare_push_origin(self):
        mod = _import_agent_runner()
        result = mod._check_protected_branch_push("Bash", {"command": "git push origin"})
        assert result is not None

    def test_blocks_force_push(self):
        mod = _import_agent_runner()
        result = mod._check_protected_branch_push("Bash", {"command": "git push --force origin feature"})
        assert result is not None

    def test_blocks_force_push_short_flag(self):
        mod = _import_agent_runner()
        result = mod._check_protected_branch_push("Bash", {"command": "git push -f origin feature"})
        assert result is not None

    def test_allows_push_to_feature_branch(self):
        mod = _import_agent_runner()
        result = mod._check_protected_branch_push("Bash", {"command": "git push origin deathstar/20260329-fix-bug"})
        assert result is None

    def test_allows_push_with_set_upstream(self):
        mod = _import_agent_runner()
        result = mod._check_protected_branch_push("Bash", {"command": "git push --set-upstream origin deathstar/feature"})
        assert result is None

    def test_ignores_non_bash_tools(self):
        mod = _import_agent_runner()
        result = mod._check_protected_branch_push("Read", {"file_path": "/tmp/main"})
        assert result is None

    def test_ignores_non_push_bash(self):
        mod = _import_agent_runner()
        result = mod._check_protected_branch_push("Bash", {"command": "git status"})
        assert result is None

    def test_string_input(self):
        mod = _import_agent_runner()
        result = mod._check_protected_branch_push("Bash", "git push origin main")
        assert result is not None


# ---------------------------------------------------------------------------
# Branch name validation (now in agent_runner)
# ---------------------------------------------------------------------------


class TestBranchValidation:
    def test_valid_branch_names(self):
        mod = _import_agent_runner()
        assert mod._validate_branch_name("feature/auth") is True
        assert mod._validate_branch_name("bugfix/login-fix") is True
        assert mod._validate_branch_name("main") is True
        assert mod._validate_branch_name("deathstar/20260329-fix") is True
        assert mod._validate_branch_name("user/john.doe/fix") is True

    def test_rejects_empty(self):
        mod = _import_agent_runner()
        assert mod._validate_branch_name("") is False

    def test_rejects_path_traversal(self):
        mod = _import_agent_runner()
        assert mod._validate_branch_name("../etc/passwd") is False
        assert mod._validate_branch_name("feature/../../etc") is False

    def test_rejects_leading_dash(self):
        mod = _import_agent_runner()
        assert mod._validate_branch_name("-bad-name") is False

    def test_rejects_lock_suffix(self):
        mod = _import_agent_runner()
        assert mod._validate_branch_name("branch.lock") is False

    def test_rejects_special_chars(self):
        mod = _import_agent_runner()
        assert mod._validate_branch_name("branch name with spaces") is False
        assert mod._validate_branch_name("branch;rm -rf /") is False

    def test_rejects_too_long(self):
        mod = _import_agent_runner()
        assert mod._validate_branch_name("a" * 257) is False
