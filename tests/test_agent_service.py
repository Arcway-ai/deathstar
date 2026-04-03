"""Tests for the Claude Agent SDK integration (agent service)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from deathstar_shared.models import WorkflowKind


# ---------------------------------------------------------------------------
# build_options
# ---------------------------------------------------------------------------


class TestBuildOptions:
    def test_prompt_mode_is_readonly(self):
        from deathstar_server.services.agent import build_options

        opts = build_options(
            workflow=WorkflowKind.PROMPT,
            cwd=Path("/tmp/repo"),
        )
        assert "Read" in opts.allowed_tools
        assert "Write" not in opts.allowed_tools
        assert opts.permission_mode == "default"

    def test_patch_mode_allows_writes(self):
        from deathstar_server.services.agent import build_options

        opts = build_options(
            workflow=WorkflowKind.PATCH,
            cwd=Path("/tmp/repo"),
        )
        assert "Write" in opts.allowed_tools
        assert "Edit" in opts.allowed_tools
        assert opts.permission_mode == "acceptEdits"

    def test_pr_mode_matches_patch(self):
        from deathstar_server.services.agent import build_options

        opts = build_options(
            workflow=WorkflowKind.PR,
            cwd=Path("/tmp/repo"),
        )
        assert "Write" in opts.allowed_tools
        assert opts.permission_mode == "acceptEdits"

    def test_review_mode(self):
        from deathstar_server.services.agent import build_options

        opts = build_options(
            workflow=WorkflowKind.REVIEW,
            cwd=Path("/tmp/repo"),
        )
        assert "Bash" in opts.allowed_tools
        assert "Write" not in opts.allowed_tools
        assert opts.permission_mode == "default"

    def test_docs_mode_allows_writes(self):
        from deathstar_server.services.agent import build_options

        opts = build_options(
            workflow=WorkflowKind.DOCS,
            cwd=Path("/tmp/repo"),
        )
        assert "Write" in opts.allowed_tools
        assert opts.permission_mode == "acceptEdits"

    def test_audit_mode_readonly(self):
        from deathstar_server.services.agent import build_options

        opts = build_options(
            workflow=WorkflowKind.AUDIT,
            cwd=Path("/tmp/repo"),
        )
        assert "Write" not in opts.allowed_tools
        assert opts.permission_mode == "default"

    def test_plan_mode_minimal_tools(self):
        from deathstar_server.services.agent import build_options

        opts = build_options(
            workflow=WorkflowKind.PLAN,
            cwd=Path("/tmp/repo"),
        )
        assert opts.allowed_tools == ["Read", "Glob", "Grep"]
        assert opts.permission_mode == "default"

    def test_system_prompt_passed(self):
        from deathstar_server.services.agent import build_options

        opts = build_options(
            workflow=WorkflowKind.PROMPT,
            cwd=Path("/tmp/repo"),
            system_prompt="Be helpful",
        )
        assert opts.system_prompt == "Be helpful"

    def test_model_passed(self):
        from deathstar_server.services.agent import build_options

        opts = build_options(
            workflow=WorkflowKind.PROMPT,
            cwd=Path("/tmp/repo"),
            model="claude-sonnet-4-5-20250514",
        )
        assert opts.model == "claude-sonnet-4-5-20250514"

    def test_session_resume(self):
        from deathstar_server.services.agent import build_options

        opts = build_options(
            workflow=WorkflowKind.PROMPT,
            cwd=Path("/tmp/repo"),
            session_id="sess-abc123",
        )
        assert opts.resume == "sess-abc123"

    def test_cwd_set(self):
        from deathstar_server.services.agent import build_options

        opts = build_options(
            workflow=WorkflowKind.PROMPT,
            cwd=Path("/workspace/projects/myrepo"),
        )
        assert opts.cwd == "/workspace/projects/myrepo"


# ---------------------------------------------------------------------------
# run_agent_stream — SSE event translation
# ---------------------------------------------------------------------------


class TestRunAgentStream:
    @pytest.mark.asyncio
    async def test_text_block_yields_delta(self):
        """AssistantMessage with TextBlock should yield a delta SSE event."""
        from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

        mock_text_block = MagicMock(spec=TextBlock)
        mock_text_block.text = "Hello world"

        mock_assistant = MagicMock(spec=AssistantMessage)
        mock_assistant.model = "claude-sonnet-4-5-20250514"
        mock_assistant.content = [mock_text_block]

        mock_result = MagicMock(spec=ResultMessage)
        mock_result.session_id = "sess-123"
        mock_result.usage = {"input_tokens": 100, "output_tokens": 50}
        mock_result.total_cost_usd = 0.01
        mock_result.is_error = False

        async def mock_query(**kwargs):
            yield mock_assistant
            yield mock_result

        with patch("deathstar_server.services.agent.query", mock_query):
            from deathstar_server.services.agent import run_agent_stream, build_options

            opts = build_options(workflow=WorkflowKind.PROMPT, cwd=Path("/tmp"))
            events = []
            async for event in run_agent_stream(
                prompt="Hello",
                options=opts,
                conversation_id="conv-1",
                workflow=WorkflowKind.PROMPT,
            ):
                events.append(event)

            # Should have at least a delta and a done event
            assert any("delta" in e for e in events)
            assert any("done" in e for e in events)
            # Verify model came from AssistantMessage
            done_event = [e for e in events if "done" in e][0]
            assert "claude-sonnet-4-5-20250514" in done_event

    @pytest.mark.asyncio
    async def test_error_yields_error_event(self):
        """Exceptions should yield an error SSE event."""
        async def mock_query(**kwargs):
            raise RuntimeError("SDK connection failed")
            yield  # make it an async generator

        with patch("deathstar_server.services.agent.query", mock_query):
            from deathstar_server.services.agent import run_agent_stream, build_options

            opts = build_options(workflow=WorkflowKind.PROMPT, cwd=Path("/tmp"))
            events = []
            async for event in run_agent_stream(
                prompt="Hello",
                options=opts,
                conversation_id="conv-1",
                workflow=WorkflowKind.PROMPT,
            ):
                events.append(event)

            assert len(events) == 1
            assert "error" in events[0]
            assert "SDK connection failed" in events[0]


# ---------------------------------------------------------------------------
# Conversation session ID methods
# ---------------------------------------------------------------------------


class TestSessionIdMethods:
    def test_update_and_get_session_id(self, tmp_path):
        from sqlmodel import SQLModel
        from deathstar_server.db.engine import create_db_engine
        from deathstar_server.web.conversations import ConversationStore

        engine = create_db_engine(f"sqlite:///{tmp_path}/test.db")
        SQLModel.metadata.create_all(engine)
        store = ConversationStore(engine)

        cid = store.get_or_create(None, "my-repo")

        # Initially no session ID
        assert store.get_session_id(cid) is None

        # Set session ID
        store.update_session_id(cid, "sdk-session-abc")
        assert store.get_session_id(cid) == "sdk-session-abc"

        # Update session ID
        store.update_session_id(cid, "sdk-session-def")
        assert store.get_session_id(cid) == "sdk-session-def"

    def test_get_session_id_nonexistent(self, tmp_path):
        from sqlmodel import SQLModel
        from deathstar_server.db.engine import create_db_engine
        from deathstar_server.web.conversations import ConversationStore

        engine = create_db_engine(f"sqlite:///{tmp_path}/test.db")
        SQLModel.metadata.create_all(engine)
        store = ConversationStore(engine)

        assert store.get_session_id("nonexistent") is None
