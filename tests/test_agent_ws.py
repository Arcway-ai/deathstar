"""Tests for the WebSocket agent endpoint and session management."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from deathstar_shared.models import WorkflowKind


# ---------------------------------------------------------------------------
# Helpers — avoid importing agent_ws at module level (it needs app_state)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_app_state():
    """Provide a mock app_state so agent_ws can import."""
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
    # Clear cached imports
    for mod_name in list(sys.modules):
        if "agent_ws" in mod_name or "agent" in mod_name:
            if mod_name.startswith("deathstar_server"):
                sys.modules.pop(mod_name, None)


def _import_agent_ws():
    # Force re-import with mocked app_state
    sys.modules.pop("deathstar_server.web.agent_ws", None)
    sys.modules.pop("deathstar_server.services.agent", None)
    from deathstar_server.web import agent_ws
    return agent_ws


# ---------------------------------------------------------------------------
# _build_options
# ---------------------------------------------------------------------------


class TestBuildOptions:
    def test_includes_partial_messages(self):
        mod = _import_agent_ws()
        opts = mod._build_options(workflow=WorkflowKind.PROMPT, cwd="/tmp/repo")
        assert opts.include_partial_messages is True

    def test_can_use_tool_injected(self):
        mod = _import_agent_ws()

        async def my_callback(name, inp, ctx):
            pass

        opts = mod._build_options(
            workflow=WorkflowKind.PROMPT, cwd="/tmp/repo", can_use_tool=my_callback,
        )
        assert opts.can_use_tool is my_callback

    def test_session_resume(self):
        mod = _import_agent_ws()
        opts = mod._build_options(
            workflow=WorkflowKind.PROMPT, cwd="/tmp", session_id="sess-123",
        )
        assert opts.resume == "sess-123"


# ---------------------------------------------------------------------------
# Session eviction
# ---------------------------------------------------------------------------


class TestSessionEviction:
    @pytest.mark.asyncio
    async def test_evicts_stale_sessions(self):
        mod = _import_agent_ws()

        mock_client = AsyncMock()

        stale = mod.AgentSession(
            conversation_id="stale-1",
            repo="test",
            branch=None,
            working_dir=Path("/tmp/test-ws/projects/test"),
            workflow=WorkflowKind.PROMPT,
            client=mock_client,
            created_at=time.time() - mod._SESSION_TTL_SECONDS - 100,
            last_active=time.time() - mod._SESSION_TTL_SECONDS - 100,
        )
        mod._sessions["stale-1"] = stale

        fresh = mod.AgentSession(
            conversation_id="fresh-1",
            repo="test",
            branch=None,
            working_dir=Path("/tmp/test-ws/projects/test"),
            workflow=WorkflowKind.PROMPT,
            client=MagicMock(),
        )
        mod._sessions["fresh-1"] = fresh

        await mod._evict_stale_sessions()

        assert "stale-1" not in mod._sessions
        assert "fresh-1" in mod._sessions
        mock_client.disconnect.assert_awaited_once()

        # Cleanup
        mod._sessions.pop("fresh-1", None)


# ---------------------------------------------------------------------------
# _usage_dict
# ---------------------------------------------------------------------------


class TestUsageDict:
    def test_dict_input(self):
        mod = _import_agent_ws()
        result = mod._usage_dict({"input_tokens": 100, "output_tokens": 50})
        assert result == {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}

    def test_none_input(self):
        mod = _import_agent_ws()
        assert mod._usage_dict(None) is None

    def test_missing_keys(self):
        mod = _import_agent_ws()
        result = mod._usage_dict({})
        assert result == {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


# ---------------------------------------------------------------------------
# _authenticate
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
# _check_protected_branch_push
# ---------------------------------------------------------------------------


class TestProtectedBranchPush:
    def test_blocks_push_to_main(self):
        mod = _import_agent_ws()
        result = mod._check_protected_branch_push("Bash", {"command": "git push origin main"})
        assert result is not None
        assert "main" in result.message.lower() or "not allowed" in result.message.lower()

    def test_blocks_push_to_master(self):
        mod = _import_agent_ws()
        result = mod._check_protected_branch_push("Bash", {"command": "git push origin master"})
        assert result is not None

    def test_blocks_bare_push(self):
        mod = _import_agent_ws()
        result = mod._check_protected_branch_push("Bash", {"command": "git push"})
        assert result is not None

    def test_blocks_bare_push_origin(self):
        mod = _import_agent_ws()
        result = mod._check_protected_branch_push("Bash", {"command": "git push origin"})
        assert result is not None

    def test_blocks_force_push(self):
        mod = _import_agent_ws()
        result = mod._check_protected_branch_push("Bash", {"command": "git push --force origin feature"})
        assert result is not None

    def test_blocks_force_push_short_flag(self):
        mod = _import_agent_ws()
        result = mod._check_protected_branch_push("Bash", {"command": "git push -f origin feature"})
        assert result is not None

    def test_allows_push_to_feature_branch(self):
        mod = _import_agent_ws()
        result = mod._check_protected_branch_push("Bash", {"command": "git push origin deathstar/20260329-fix-bug"})
        assert result is None

    def test_allows_push_with_set_upstream(self):
        mod = _import_agent_ws()
        result = mod._check_protected_branch_push("Bash", {"command": "git push --set-upstream origin deathstar/feature"})
        assert result is None

    def test_ignores_non_bash_tools(self):
        mod = _import_agent_ws()
        result = mod._check_protected_branch_push("Read", {"file_path": "/tmp/main"})
        assert result is None

    def test_ignores_non_push_bash(self):
        mod = _import_agent_ws()
        result = mod._check_protected_branch_push("Bash", {"command": "git status"})
        assert result is None

    def test_string_input(self):
        mod = _import_agent_ws()
        result = mod._check_protected_branch_push("Bash", "git push origin main")
        assert result is not None


# ---------------------------------------------------------------------------
# Branch locking lifecycle
# ---------------------------------------------------------------------------


class TestBranchLocking:
    def test_release_session_removes_lock(self):
        mod = _import_agent_ws()
        session = mod.AgentSession(
            conversation_id="lock-test-1",
            repo="my-repo",
            branch="feature/x",
            working_dir=Path("/tmp/test-ws/projects/my-repo"),
            workflow=WorkflowKind.PROMPT,
            client=MagicMock(),
        )
        mod._sessions["lock-test-1"] = session
        mod._branch_locks[("my-repo", "feature/x")] = "lock-test-1"

        mod._release_session(session)

        assert "lock-test-1" not in mod._sessions
        assert ("my-repo", "feature/x") not in mod._branch_locks

    def test_release_session_does_not_remove_other_lock(self):
        mod = _import_agent_ws()
        session = mod.AgentSession(
            conversation_id="lock-test-2",
            repo="my-repo",
            branch="feature/y",
            working_dir=Path("/tmp/test-ws/projects/my-repo"),
            workflow=WorkflowKind.PROMPT,
            client=MagicMock(),
        )
        mod._sessions["lock-test-2"] = session
        # Lock held by a different session
        mod._branch_locks[("my-repo", "feature/y")] = "someone-else"

        mod._release_session(session)

        assert "lock-test-2" not in mod._sessions
        # Lock should NOT be removed since it belongs to a different session
        assert mod._branch_locks[("my-repo", "feature/y")] == "someone-else"

        # Cleanup
        mod._branch_locks.pop(("my-repo", "feature/y"), None)

    def test_release_session_no_branch(self):
        mod = _import_agent_ws()
        session = mod.AgentSession(
            conversation_id="lock-test-3",
            repo="my-repo",
            branch=None,
            working_dir=Path("/tmp/test-ws/projects/my-repo"),
            workflow=WorkflowKind.PROMPT,
            client=MagicMock(),
        )
        mod._sessions["lock-test-3"] = session

        mod._release_session(session)

        assert "lock-test-3" not in mod._sessions

    def test_get_active_branches_returns_snapshot(self):
        mod = _import_agent_ws()
        mod._branch_locks[("repo-a", "branch-1")] = "conv-1"
        mod._branch_locks[("repo-a", "branch-2")] = "conv-2"

        snapshot = mod.get_active_branches()

        assert snapshot == {("repo-a", "branch-1"): "conv-1", ("repo-a", "branch-2"): "conv-2"}
        # Snapshot should be a copy
        snapshot[("repo-a", "branch-3")] = "conv-3"
        assert ("repo-a", "branch-3") not in mod._branch_locks

        # Cleanup
        mod._branch_locks.pop(("repo-a", "branch-1"), None)
        mod._branch_locks.pop(("repo-a", "branch-2"), None)


# ---------------------------------------------------------------------------
# Branch name validation
# ---------------------------------------------------------------------------


class TestBranchValidation:
    def test_valid_branch_names(self):
        mod = _import_agent_ws()
        assert mod._validate_branch_name("feature/auth") is True
        assert mod._validate_branch_name("bugfix/login-fix") is True
        assert mod._validate_branch_name("main") is True
        assert mod._validate_branch_name("deathstar/20260329-fix") is True
        assert mod._validate_branch_name("user/john.doe/fix") is True

    def test_rejects_empty(self):
        mod = _import_agent_ws()
        assert mod._validate_branch_name("") is False

    def test_rejects_path_traversal(self):
        mod = _import_agent_ws()
        assert mod._validate_branch_name("../etc/passwd") is False
        assert mod._validate_branch_name("feature/../../etc") is False

    def test_rejects_leading_dash(self):
        mod = _import_agent_ws()
        assert mod._validate_branch_name("-bad-name") is False

    def test_rejects_lock_suffix(self):
        mod = _import_agent_ws()
        assert mod._validate_branch_name("branch.lock") is False

    def test_rejects_special_chars(self):
        mod = _import_agent_ws()
        assert mod._validate_branch_name("branch name with spaces") is False
        assert mod._validate_branch_name("branch;rm -rf /") is False

    def test_rejects_too_long(self):
        mod = _import_agent_ws()
        assert mod._validate_branch_name("a" * 257) is False
