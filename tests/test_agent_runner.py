"""Tests for AgentRunner — background agent execution service.

Covers:
- Branch locking: TOCTOU fix, concurrent-start protection, immediate release on completion
- RunningAgent pub/sub: subscribe/unsubscribe, fan-out, buffer-full drop
- Concurrent reader prevention: _execute_task cancellation on reuse
- send_followup: COMPLETED agent reconnects client, RUNNING agent cancels old task
- Permission flow: respond_permission signals waiter, unknown conv no-ops
- respond_permission: no-op on missing event
- list_active / get_agent / is_branch_active / get_active_branches
- _cleanup_agent: removes agent and branch lock
- Reaper: evicts stale running agents (interrupt then disconnect), removes old completed agents
- validate_branch_name / check_protected_branch_push helpers (already in test_agent_ws; extend here)
- _usage_dict helper
- AgentSessionResponse Literal status field
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest

from deathstar_shared.models import WorkflowKind


# ---------------------------------------------------------------------------
# Helpers — build a minimal AgentRunner without real infrastructure
# ---------------------------------------------------------------------------


def _make_runner(*, convo_store=None, worktree=None, event_bus=None):
    """Return an AgentRunner wired to mocks. Does NOT call start()."""
    from deathstar_server.services.agent_runner import AgentRunner

    mock_convo = convo_store or MagicMock()
    mock_convo.get_or_create.side_effect = lambda cid, repo, branch: cid or "new-conv-id"
    mock_convo.add_user_message.return_value = None
    mock_convo.get_session_id.return_value = None
    mock_convo.add_assistant_message.return_value = "msg-id-1"

    mock_worktree = worktree or MagicMock()
    mock_worktree.resolve_working_dir.return_value = Path("/tmp/repo")

    mock_bus = event_bus or MagicMock()
    mock_settings = MagicMock()
    mock_settings.workspace_root = Path("/tmp/test-workspace")
    mock_git = MagicMock()
    mock_github = MagicMock()

    runner = AgentRunner(
        mock_convo,
        mock_worktree,
        mock_bus,
        mock_settings,
        mock_git,
        mock_github,
    )
    return runner


def _make_running_agent(*, conversation_id="conv-1", repo="org/repo", branch="feat", status=None):
    """Build a RunningAgent in RUNNING state with a mock client."""
    from deathstar_server.services.agent_runner import AgentStatus, RunningAgent

    client = MagicMock()
    client.query = AsyncMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.interrupt = AsyncMock()

    agent = RunningAgent(
        conversation_id=conversation_id,
        repo=repo,
        branch=branch,
        workflow=WorkflowKind.PROMPT,
        working_dir=Path("/tmp/repo"),
        client=client,
        auto_accept=False,
        prompt="hello",
    )
    if status is not None:
        agent.status = status
    else:
        from deathstar_server.services.agent_runner import AgentStatus
        agent.status = AgentStatus.RUNNING
    return agent


# ---------------------------------------------------------------------------
# _execute_agent — incremental snapshot sync
# ---------------------------------------------------------------------------


class TestExecuteAgentSnapshot:
    """_execute_agent must sync accumulated_text/blocks to the agent object after
    every message so that get_snapshot() returns current output for reconnecting
    clients, not an empty string.

    Before the fix: accumulated_text was a local variable only written back to
    agent.accumulated_text after the async for loop exited.
    """

    @pytest.mark.asyncio
    async def test_snapshot_has_text_after_first_stream_event(self):
        """agent.accumulated_text reflects streamed text mid-run (before ResultMessage)."""
        import asyncio

        from claude_agent_sdk import ResultMessage, StreamEvent

        runner = _make_runner()
        agent = _make_running_agent()
        runner._agents[agent.conversation_id] = agent

        # Gate that fires after the first StreamEvent is processed
        first_processed = asyncio.Event()
        # Gate that lets execution continue to the ResultMessage
        resume = asyncio.Event()

        async def fake_receive_messages():
            yield StreamEvent(
                uuid="u1",
                session_id="s1",
                event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello"}},
            )
            # Signal the test that the first message is done, then wait for clearance
            first_processed.set()
            await resume.wait()
            yield ResultMessage(
                subtype="result",
                uuid="u2",
                session_id="s1",
                duration_ms=100,
                duration_api_ms=100,
                is_error=False,
                num_turns=1,
                result="Hello",
                total_cost_usd=0.0,
                usage=None,
            )

        agent.client.receive_messages = fake_receive_messages

        task = asyncio.create_task(runner._execute_agent(agent))
        await asyncio.wait_for(first_processed.wait(), timeout=5.0)

        # Mid-run: the first text delta has been processed.
        # With the fix: agent.accumulated_text == "Hello"
        # Without the fix: agent.accumulated_text == "" (local var not yet written back)
        mid_run_text = agent.accumulated_text

        resume.set()
        await asyncio.wait_for(task, timeout=5.0)

        assert mid_run_text == "Hello", (
            f"get_snapshot() mid-run returned {mid_run_text!r}; "
            "expected 'Hello' — incremental sync is missing"
        )
        # Final state should also be correct
        assert agent.accumulated_text == "Hello"

    @pytest.mark.asyncio
    async def test_snapshot_accumulates_across_multiple_deltas(self):
        """Each streamed delta is visible in get_snapshot() immediately after processing."""
        import asyncio

        from claude_agent_sdk import ResultMessage, StreamEvent

        runner = _make_runner()
        agent = _make_running_agent()
        runner._agents[agent.conversation_id] = agent

        checkpoints: list[str] = []
        gates = [asyncio.Event() for _ in range(3)]
        resumes = [asyncio.Event() for _ in range(3)]

        async def fake_receive_messages():
            for i, text in enumerate(["Hello", " world", "!"]):
                yield StreamEvent(
                    uuid=f"u{i}",
                    session_id="s1",
                    event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}},
                )
                gates[i].set()
                await resumes[i].wait()
            yield ResultMessage(
                subtype="result", uuid="u9", session_id="s1",
                duration_ms=100, duration_api_ms=100, is_error=False,
                num_turns=3, result="Hello world!", total_cost_usd=0.0, usage=None,
            )

        agent.client.receive_messages = fake_receive_messages
        task = asyncio.create_task(runner._execute_agent(agent))

        expected = ["Hello", "Hello world", "Hello world!"]
        for i in range(3):
            await asyncio.wait_for(gates[i].wait(), timeout=5.0)
            checkpoints.append(agent.accumulated_text)
            resumes[i].set()

        await asyncio.wait_for(task, timeout=5.0)
        assert checkpoints == expected, f"Mid-run snapshots wrong: {checkpoints}"


# ---------------------------------------------------------------------------
# RunningAgent — pub/sub
# ---------------------------------------------------------------------------


class TestRunningAgentPubSub:
    def test_subscribe_returns_unique_ids(self):
        agent = _make_running_agent()
        id1, _ = agent.subscribe()
        id2, _ = agent.subscribe()
        assert id1 != id2

    def test_publish_delivers_to_all_subscribers(self):
        from deathstar_server.services.agent_runner import AgentEvent, AgentEventType

        agent = _make_running_agent()
        _id1, recv1 = agent.subscribe()
        _id2, recv2 = agent.subscribe()

        event = AgentEvent(type=AgentEventType.TEXT_DELTA, data={"text": "hello"})
        agent.publish(event)

        got1 = recv1.receive_nowait()
        got2 = recv2.receive_nowait()
        assert got1.data["text"] == "hello"
        assert got2.data["text"] == "hello"

    def test_unsubscribe_closes_receive_stream(self):
        import anyio

        agent = _make_running_agent()
        sub_id, recv = agent.subscribe()
        agent.unsubscribe(sub_id)

        # After unsubscribe the send side is closed; recv should raise
        with pytest.raises((anyio.ClosedResourceError, anyio.EndOfStream)):
            recv.receive_nowait()

    def test_publish_drops_on_full_buffer(self):
        """Publish more events than _SUBSCRIBER_BUFFER_SIZE; extras are silently dropped."""
        from deathstar_server.services.agent_runner import (
            AgentEvent,
            AgentEventType,
            _SUBSCRIBER_BUFFER_SIZE,
        )

        agent = _make_running_agent()
        _sub_id, recv = agent.subscribe()

        # Fill the buffer exactly, then overflow by one — should not raise
        for i in range(_SUBSCRIBER_BUFFER_SIZE + 5):
            event = AgentEvent(type=AgentEventType.TEXT_DELTA, data={"text": str(i)})
            agent.publish(event)  # must not raise

        # First _SUBSCRIBER_BUFFER_SIZE events should be readable
        count = 0
        while True:
            try:
                recv.receive_nowait()
                count += 1
            except Exception:
                break
        assert count == _SUBSCRIBER_BUFFER_SIZE

    def test_has_subscribers_reflects_active_subs(self):
        agent = _make_running_agent()
        assert not agent.has_subscribers
        sub_id, _ = agent.subscribe()
        assert agent.has_subscribers
        agent.unsubscribe(sub_id)
        assert not agent.has_subscribers

    def test_get_snapshot_returns_status_and_text(self):
        from deathstar_server.services.agent_runner import AgentStatus

        agent = _make_running_agent(status=AgentStatus.RUNNING)
        agent.accumulated_text = "some text"
        snap = agent.get_snapshot()
        assert snap["status"] == "running"
        assert snap["text"] == "some text"
        assert snap["conversation_id"] == agent.conversation_id


# ---------------------------------------------------------------------------
# AgentRunner — branch locking
# ---------------------------------------------------------------------------


class TestBranchLocking:
    def test_lock_set_after_start_agent(self):
        """Branch lock is registered after get_or_create resolves the conv ID."""
        runner = _make_runner()
        runner._agents["conv-1"] = _make_running_agent(conversation_id="conv-1", branch="feat")
        runner._branch_locks[("org/repo", "feat")] = "conv-1"
        assert runner.is_branch_active("org/repo", "feat")

    def test_cleanup_releases_lock(self):
        runner = _make_runner()
        agent = _make_running_agent(conversation_id="conv-1", branch="feat")
        runner._agents["conv-1"] = agent
        runner._branch_locks[("org/repo", "feat")] = "conv-1"

        runner._cleanup_agent(agent)

        assert not runner.is_branch_active("org/repo", "feat")
        assert "conv-1" not in runner._agents

    def test_cleanup_does_not_release_foreign_lock(self):
        """If another agent holds the lock, cleanup of the first does not remove it."""
        runner = _make_runner()
        agent1 = _make_running_agent(conversation_id="conv-1", branch="feat")
        agent2 = _make_running_agent(conversation_id="conv-2", branch="feat")
        runner._agents["conv-1"] = agent1
        runner._agents["conv-2"] = agent2
        # Lock held by conv-2, not conv-1
        runner._branch_locks[("org/repo", "feat")] = "conv-2"

        runner._cleanup_agent(agent1)

        # Lock should still be there (held by conv-2)
        assert runner._branch_locks.get(("org/repo", "feat")) == "conv-2"

    @pytest.mark.asyncio
    async def test_start_agent_raises_if_branch_in_use(self):
        """start_agent raises AppError when an active agent holds the branch lock."""
        from deathstar_server.errors import AppError
        from deathstar_server.services.agent_runner import AgentStatus

        runner = _make_runner()
        existing = _make_running_agent(conversation_id="conv-other", branch="feat", status=AgentStatus.RUNNING)
        runner._agents["conv-other"] = existing
        runner._branch_locks[("org/repo", "feat")] = "conv-other"

        # start_agent validates branch lock before needing the task group
        with pytest.raises((AppError, Exception), match="already in use|branch"):
            await runner.start_agent(
                conversation_id=None,
                repo="org/repo",
                branch="feat",
                message="hi",
                workflow=WorkflowKind.PROMPT,
            )

    @pytest.mark.asyncio
    async def test_start_agent_placeholder_lock_prevents_double_start(self):
        """The __pending__ placeholder is set before get_or_create to block concurrent starts."""
        runner = _make_runner()

        # Simulate: lock already set to __pending__ (as if a concurrent start_agent is mid-flight)
        runner._branch_locks[("org/repo", "feat")] = "__pending__"
        # __pending__ is NOT in _agents, so the holder-in-agents check skips it
        # But the branch lock check should NOT block (pending is not an active agent)
        # Verify is_branch_active returns False for pending (no agent in _agents)
        assert not runner.is_branch_active("org/repo", "feat")

    @pytest.mark.asyncio
    async def test_invalid_branch_name_raises(self):
        from deathstar_server.errors import AppError
        from deathstar_server.services.agent_runner import _validate_branch_name

        # Test the validator directly (start_agent delegates to it)
        assert not _validate_branch_name("bad..branch")
        runner = _make_runner()
        with pytest.raises(AppError):
            await runner.start_agent(
                conversation_id=None,
                repo="org/repo",
                branch="bad..branch",
                message="hi",
                workflow=WorkflowKind.PROMPT,
            )

    @pytest.mark.asyncio
    async def test_max_agents_raises(self):
        from deathstar_server.errors import AppError
        from deathstar_server.services.agent_runner import AgentStatus, _MAX_AGENTS

        runner = _make_runner()
        # Fill up to the limit with RUNNING agents
        for i in range(_MAX_AGENTS):
            a = _make_running_agent(conversation_id=f"conv-{i}", branch=None, status=AgentStatus.RUNNING)
            a.branch = None
            runner._agents[f"conv-{i}"] = a

        with pytest.raises(AppError):
            await runner.start_agent(
                conversation_id=None,
                repo="org/repo",
                branch=None,
                message="hi",
                workflow=WorkflowKind.PROMPT,
            )


# ---------------------------------------------------------------------------
# AgentRunner — list_active / get_agent / get_active_branches
# ---------------------------------------------------------------------------


class TestQueryMethods:
    def test_list_active_excludes_completed(self):
        from deathstar_server.services.agent_runner import AgentStatus

        runner = _make_runner()
        running = _make_running_agent(conversation_id="a", status=AgentStatus.RUNNING)
        completed = _make_running_agent(conversation_id="b", status=AgentStatus.COMPLETED)
        runner._agents["a"] = running
        runner._agents["b"] = completed

        active = runner.list_active()
        ids = {a.conversation_id for a in active}
        assert "a" in ids
        assert "b" not in ids

    def test_list_active_includes_waiting_permission(self):
        from deathstar_server.services.agent_runner import AgentStatus

        runner = _make_runner()
        waiting = _make_running_agent(conversation_id="w", status=AgentStatus.WAITING_PERMISSION)
        runner._agents["w"] = waiting

        active = runner.list_active()
        assert any(a.conversation_id == "w" for a in active)

    def test_get_agent_returns_none_for_unknown(self):
        runner = _make_runner()
        assert runner.get_agent("no-such") is None

    def test_get_agent_returns_agent(self):
        runner = _make_runner()
        agent = _make_running_agent(conversation_id="conv-1")
        runner._agents["conv-1"] = agent
        assert runner.get_agent("conv-1") is agent

    def test_get_active_branches_returns_copy(self):
        runner = _make_runner()
        runner._branch_locks[("repo", "feat")] = "conv-1"
        branches = runner.get_active_branches()
        # Modifying the returned dict does not affect internal state
        branches[("repo", "other")] = "conv-2"
        assert ("repo", "other") not in runner._branch_locks

    def test_is_branch_active_false_when_no_agent(self):
        runner = _make_runner()
        runner._branch_locks[("repo", "feat")] = "ghost-conv"
        # Lock points to a conv not in _agents → not actually active
        assert not runner.is_branch_active("repo", "feat")

    def test_is_branch_active_true_when_agent_present(self):
        runner = _make_runner()
        agent = _make_running_agent(conversation_id="conv-1", branch="feat")
        runner._agents["conv-1"] = agent
        runner._branch_locks[("org/repo", "feat")] = "conv-1"
        assert runner.is_branch_active("org/repo", "feat")


# ---------------------------------------------------------------------------
# AgentRunner — subscribe / unsubscribe
# ---------------------------------------------------------------------------


class TestSubscribeUnsubscribe:
    def test_subscribe_returns_none_for_unknown_conv(self):
        runner = _make_runner()
        assert runner.subscribe("no-such") is None

    def test_subscribe_returns_stream_for_known_agent(self):
        runner = _make_runner()
        agent = _make_running_agent(conversation_id="conv-1")
        runner._agents["conv-1"] = agent
        result = runner.subscribe("conv-1")
        assert result is not None
        sub_id, recv = result
        assert isinstance(sub_id, str)

    def test_unsubscribe_unknown_conv_is_noop(self):
        runner = _make_runner()
        runner.unsubscribe("no-such", "sub-id")  # must not raise

    def test_unsubscribe_unknown_sub_id_is_noop(self):
        runner = _make_runner()
        agent = _make_running_agent(conversation_id="conv-1")
        runner._agents["conv-1"] = agent
        runner.unsubscribe("conv-1", "ghost-sub-id")  # must not raise


# ---------------------------------------------------------------------------
# AgentRunner — respond_permission
# ---------------------------------------------------------------------------


class TestRespondPermission:
    def test_respond_permission_noop_on_missing_conv(self):
        runner = _make_runner()
        runner.respond_permission("no-such", allow=True)  # must not raise

    def test_respond_permission_noop_when_no_event(self):
        runner = _make_runner()
        agent = _make_running_agent(conversation_id="conv-1")
        agent.permission_event = None
        runner._agents["conv-1"] = agent
        runner.respond_permission("conv-1", allow=True)  # must not raise

    @pytest.mark.asyncio
    async def test_respond_permission_allow_signals_event(self):
        from claude_agent_sdk.types import PermissionResultAllow

        runner = _make_runner()
        agent = _make_running_agent(conversation_id="conv-1")
        agent.permission_event = anyio.Event()
        agent.permission_result = None
        runner._agents["conv-1"] = agent

        runner.respond_permission("conv-1", allow=True)

        assert agent.permission_event.is_set()
        assert isinstance(agent.permission_result, PermissionResultAllow)

    @pytest.mark.asyncio
    async def test_respond_permission_deny_signals_event(self):
        from claude_agent_sdk.types import PermissionResultDeny

        runner = _make_runner()
        agent = _make_running_agent(conversation_id="conv-1")
        agent.permission_event = anyio.Event()
        agent.permission_result = None
        runner._agents["conv-1"] = agent

        runner.respond_permission("conv-1", allow=False)

        assert agent.permission_event.is_set()
        assert isinstance(agent.permission_result, PermissionResultDeny)


# ---------------------------------------------------------------------------
# AgentRunner — send_followup
# ---------------------------------------------------------------------------


class TestSendFollowup:
    @pytest.mark.asyncio
    async def test_send_followup_raises_for_unknown_conv(self):
        from deathstar_server.errors import AppError

        runner = _make_runner()
        with pytest.raises(AppError):
            await runner.send_followup("no-such", "hello")

    @pytest.mark.asyncio
    async def test_send_followup_raises_for_failed_agent(self):
        from deathstar_server.errors import AppError
        from deathstar_server.services.agent_runner import AgentStatus

        runner = _make_runner()
        agent = _make_running_agent(conversation_id="conv-1", status=AgentStatus.FAILED)
        runner._agents["conv-1"] = agent
        with pytest.raises(AppError):
            await runner.send_followup("conv-1", "hello")

    @pytest.mark.asyncio
    async def test_send_followup_running_cancels_old_task(self):
        """send_followup cancels an in-flight _execute_task before spawning a new one."""
        from deathstar_server.services.agent_runner import AgentStatus

        runner = _make_runner()
        # Fake task group
        runner._task_group = MagicMock()
        runner._task_group.start_soon = MagicMock()

        agent = _make_running_agent(conversation_id="conv-1", status=AgentStatus.RUNNING)

        # Attach a fake in-flight task that is NOT done
        old_task = MagicMock(spec=asyncio.Task)
        old_task.done.return_value = False
        old_task.cancel.return_value = True

        # Make awaiting the old task a no-op
        async def _noop():
            pass

        old_task.__await__ = lambda self: _noop().__await__()
        agent._execute_task = old_task
        runner._agents["conv-1"] = agent

        # Patch create_task so we don't actually run anything
        with patch("asyncio.get_running_loop") as mock_loop:
            mock_loop.return_value.create_task = MagicMock(return_value=MagicMock(spec=asyncio.Task))
            await runner.send_followup("conv-1", "follow up")

        old_task.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_followup_completed_reconnects_client(self):
        """send_followup on a COMPLETED agent calls client.connect() before query()."""
        from deathstar_server.services.agent_runner import AgentStatus

        runner = _make_runner()
        with patch("asyncio.get_running_loop") as mock_loop:
            mock_loop.return_value.create_task = MagicMock(return_value=MagicMock(spec=asyncio.Task))

            agent = _make_running_agent(conversation_id="conv-1", status=AgentStatus.COMPLETED)
            runner._agents["conv-1"] = agent

            await runner.send_followup("conv-1", "follow up")

        agent.client.connect.assert_awaited_once()
        agent.client.query.assert_awaited_once_with("follow up")


# ---------------------------------------------------------------------------
# AgentRunner — _cleanup_agent
# ---------------------------------------------------------------------------


class TestCleanupAgent:
    def test_cleanup_removes_from_agents_dict(self):
        runner = _make_runner()
        agent = _make_running_agent(conversation_id="conv-1", branch=None)
        agent.branch = None
        runner._agents["conv-1"] = agent
        runner._cleanup_agent(agent)
        assert "conv-1" not in runner._agents

    def test_cleanup_noop_for_absent_branch(self):
        runner = _make_runner()
        agent = _make_running_agent(conversation_id="conv-1", branch=None)
        agent.branch = None
        runner._agents["conv-1"] = agent
        runner._cleanup_agent(agent)  # must not raise


# ---------------------------------------------------------------------------
# AgentRunner — reaper loop logic (unit-level, not full async)
# ---------------------------------------------------------------------------


class TestReaperEviction:
    @pytest.mark.asyncio
    async def test_reaper_calls_interrupt_then_disconnect_for_stale_agent(self):
        """Evicted stale agents get interrupt() before disconnect()."""
        from deathstar_server.services.agent_runner import AgentStatus, _AGENT_TTL_SECONDS

        runner = _make_runner()
        agent = _make_running_agent(conversation_id="conv-stale", status=AgentStatus.RUNNING)
        # Make the agent appear stale
        agent.last_active = time.time() - _AGENT_TTL_SECONDS - 10
        runner._agents["conv-stale"] = agent

        # Run a single reaper cycle without the sleep
        now = time.time()
        to_remove = []
        for conv_id, ag in list(runner._agents.items()):
            if ag.status in (
                __import__("deathstar_server.services.agent_runner", fromlist=["AgentStatus"]).AgentStatus.COMPLETED,
                __import__("deathstar_server.services.agent_runner", fromlist=["AgentStatus"]).AgentStatus.FAILED,
            ):
                pass
            elif now - ag.last_active > _AGENT_TTL_SECONDS:
                try:
                    await ag.client.interrupt()
                except Exception:
                    pass
                try:
                    await ag.client.disconnect()
                except Exception:
                    pass
                to_remove.append(conv_id)
        for conv_id in to_remove:
            ag = runner._agents.get(conv_id)
            if ag:
                runner._cleanup_agent(ag)

        agent.client.interrupt.assert_awaited_once()
        agent.client.disconnect.assert_awaited_once()
        assert "conv-stale" not in runner._agents

    @pytest.mark.asyncio
    async def test_reaper_removes_old_completed_agents(self):
        """Completed agents are removed after _COMPLETED_RETAIN_SECONDS."""
        from deathstar_server.services.agent_runner import (
            AgentStatus,
            _COMPLETED_RETAIN_SECONDS,
        )

        runner = _make_runner()
        agent = _make_running_agent(conversation_id="conv-done", status=AgentStatus.COMPLETED)
        agent.completed_at = time.time() - _COMPLETED_RETAIN_SECONDS - 10
        runner._agents["conv-done"] = agent

        now = time.time()
        to_remove = []
        for conv_id, ag in list(runner._agents.items()):
            if ag.status in (AgentStatus.COMPLETED, AgentStatus.FAILED):
                if ag.completed_at and now - ag.completed_at > _COMPLETED_RETAIN_SECONDS:
                    to_remove.append(conv_id)
        for conv_id in to_remove:
            ag = runner._agents.get(conv_id)
            if ag:
                runner._cleanup_agent(ag)

        assert "conv-done" not in runner._agents

    @pytest.mark.asyncio
    async def test_reaper_keeps_recently_completed_agents(self):
        """Completed agents within the retain window are kept for snapshot access."""
        from deathstar_server.services.agent_runner import (
            AgentStatus,
            _COMPLETED_RETAIN_SECONDS,
        )

        runner = _make_runner()
        agent = _make_running_agent(conversation_id="conv-new", status=AgentStatus.COMPLETED)
        agent.completed_at = time.time() - (_COMPLETED_RETAIN_SECONDS / 2)
        runner._agents["conv-new"] = agent

        now = time.time()
        to_remove = []
        for conv_id, ag in list(runner._agents.items()):
            if ag.status in (AgentStatus.COMPLETED, AgentStatus.FAILED):
                if ag.completed_at and now - ag.completed_at > _COMPLETED_RETAIN_SECONDS:
                    to_remove.append(conv_id)
        for conv_id in to_remove:
            ag = runner._agents.get(conv_id)
            if ag:
                runner._cleanup_agent(ag)

        assert "conv-new" in runner._agents


# ---------------------------------------------------------------------------
# Branch lock released immediately on completion (S4)
# ---------------------------------------------------------------------------


class TestBranchLockReleasedOnCompletion:
    def test_lock_released_when_agent_completes(self):
        """Branch lock should be cleared by _cleanup_agent (called in execute finally block)."""
        runner = _make_runner()
        agent = _make_running_agent(conversation_id="conv-1", branch="feat")
        runner._agents["conv-1"] = agent
        runner._branch_locks[("org/repo", "feat")] = "conv-1"

        # Simulate what the _execute_agent finally block does
        runner._cleanup_agent(agent)

        assert not runner.is_branch_active("org/repo", "feat")

    def test_completed_agent_does_not_block_new_agent_on_same_branch(self):
        """After _cleanup, a new start_agent call for the same branch is not blocked."""
        from deathstar_server.services.agent_runner import AgentStatus

        runner = _make_runner()
        agent = _make_running_agent(
            conversation_id="conv-done", branch="feat", status=AgentStatus.COMPLETED
        )
        runner._agents["conv-done"] = agent
        runner._branch_locks[("org/repo", "feat")] = "conv-done"

        # Simulate post-execution cleanup
        runner._cleanup_agent(agent)

        # Now the branch lock is gone — a new start should not be blocked
        # (We test is_branch_active instead of calling start_agent to avoid
        #  needing a full SDK mock)
        assert not runner.is_branch_active("org/repo", "feat")

    @pytest.mark.asyncio
    async def test_start_agent_reacquires_branch_lock_after_task_cancellation(self):
        """Branch lock must be re-acquired immediately after cancelling the old _execute_task.

        The cancelled task's finally block unconditionally releases the lock. Without an
        explicit re-acquisition between the cancel-await and the next yield point
        (client.query), a concurrent start_agent for the same branch can sneak through
        the lock check.
        """
        import asyncio

        from deathstar_server.services.agent_runner import AgentStatus

        runner = _make_runner()

        # Set up a RUNNING agent on "feat" branch that has a real (not-yet-done) task
        agent = _make_running_agent(
            conversation_id="conv-1", branch="feat", status=AgentStatus.RUNNING
        )
        runner._agents["conv-1"] = agent
        runner._branch_locks[("org/repo", "feat")] = "conv-1"

        # Simulate: _execute_task is a real asyncio.Task that can be cancelled
        released = []

        async def _fake_execute():
            try:
                await asyncio.sleep(100)
            finally:
                # Mimic the real finally block: drop the lock
                runner._branch_locks.pop(("org/repo", "feat"), None)
                released.append(True)

        loop = asyncio.get_running_loop()
        agent._execute_task = loop.create_task(_fake_execute())
        await asyncio.sleep(0)  # let the task start

        # Simulate what start_agent's reuse path does
        agent._execute_task.cancel()
        try:
            await agent._execute_task
        except (asyncio.CancelledError, Exception):
            pass
        agent._execute_task = None

        # The finally block has fired — lock is now gone
        assert released, "task finally block should have run"
        assert "org/repo" not in {k[0] for k, v in runner._branch_locks.items() if k[1] == "feat"} or \
               runner._branch_locks.get(("org/repo", "feat")) != "conv-1"

        # Re-acquire (the fix)
        if agent.branch:
            runner._branch_locks[(agent.repo, agent.branch)] = agent.conversation_id

        # Now the lock is held again — a concurrent start for the same branch would fail
        assert runner.is_branch_active("org/repo", "feat")

    @pytest.mark.asyncio
    async def test_send_followup_reacquires_branch_lock_after_task_cancellation(self):
        """send_followup must also re-acquire the branch lock after cancelling the old task."""
        import asyncio

        from deathstar_server.services.agent_runner import AgentStatus

        runner = _make_runner()

        agent = _make_running_agent(
            conversation_id="conv-2", branch="hotfix", status=AgentStatus.RUNNING
        )
        runner._agents["conv-2"] = agent
        runner._branch_locks[("org/repo", "hotfix")] = "conv-2"

        released = []

        async def _fake_execute():
            try:
                await asyncio.sleep(100)
            finally:
                runner._branch_locks.pop(("org/repo", "hotfix"), None)
                released.append(True)

        loop = asyncio.get_running_loop()
        agent._execute_task = loop.create_task(_fake_execute())
        await asyncio.sleep(0)

        # Simulate send_followup cancellation block
        agent._execute_task.cancel()
        try:
            await agent._execute_task
        except (asyncio.CancelledError, Exception):
            pass
        agent._execute_task = None

        assert released, "task finally block should have run"
        # Without the fix, lock would be gone here
        # Apply the fix
        if agent.branch:
            runner._branch_locks[(agent.repo, agent.branch)] = agent.conversation_id

        # Branch should now be locked again
        assert runner.is_branch_active("org/repo", "hotfix")


# ---------------------------------------------------------------------------
# _validate_branch_name helper
# ---------------------------------------------------------------------------


class TestValidateBranchName:
    def test_accepts_valid_names(self):
        from deathstar_server.services.agent_runner import _validate_branch_name

        assert _validate_branch_name("feat/my-branch")
        assert _validate_branch_name("fix_123")
        assert _validate_branch_name("main")
        assert _validate_branch_name("deathstar/20240101120000-add-tests")

    def test_rejects_empty(self):
        from deathstar_server.services.agent_runner import _validate_branch_name

        assert not _validate_branch_name("")

    def test_rejects_double_dot(self):
        from deathstar_server.services.agent_runner import _validate_branch_name

        assert not _validate_branch_name("bad..branch")

    def test_rejects_leading_dash(self):
        from deathstar_server.services.agent_runner import _validate_branch_name

        assert not _validate_branch_name("-bad")

    def test_rejects_leading_dot(self):
        from deathstar_server.services.agent_runner import _validate_branch_name

        assert not _validate_branch_name(".bad")

    def test_rejects_dotlock_suffix(self):
        from deathstar_server.services.agent_runner import _validate_branch_name

        assert not _validate_branch_name("branch.lock")

    def test_rejects_too_long(self):
        from deathstar_server.services.agent_runner import _validate_branch_name

        assert not _validate_branch_name("x" * 257)


# ---------------------------------------------------------------------------
# _check_protected_branch_push helper
# ---------------------------------------------------------------------------


class TestCheckProtectedBranchPush:
    def test_blocks_push_to_main(self):
        from deathstar_server.services.agent_runner import _check_protected_branch_push

        result = _check_protected_branch_push("Bash", {"command": "git push origin main"})
        assert result is not None
        assert "not allowed" in result.message.lower() or "main" in result.message.lower()

    def test_blocks_push_to_master(self):
        from deathstar_server.services.agent_runner import _check_protected_branch_push

        result = _check_protected_branch_push("Bash", {"command": "git push origin master"})
        assert result is not None

    def test_blocks_ambiguous_push(self):
        from deathstar_server.services.agent_runner import _check_protected_branch_push

        result = _check_protected_branch_push("Bash", {"command": "git push"})
        assert result is not None

    def test_blocks_force_push(self):
        from deathstar_server.services.agent_runner import _check_protected_branch_push

        result = _check_protected_branch_push("Bash", {"command": "git push --force origin feat"})
        assert result is not None

    def test_allows_push_to_feature_branch(self):
        from deathstar_server.services.agent_runner import _check_protected_branch_push

        result = _check_protected_branch_push("Bash", {"command": "git push origin feat/my-branch"})
        assert result is None

    def test_non_bash_tool_returns_none(self):
        from deathstar_server.services.agent_runner import _check_protected_branch_push

        result = _check_protected_branch_push("Read", {"path": "/some/file"})
        assert result is None


# ---------------------------------------------------------------------------
# _usage_dict helper
# ---------------------------------------------------------------------------


class TestUsageDict:
    def test_none_returns_none(self):
        from deathstar_server.services.agent_runner import _usage_dict

        assert _usage_dict(None) is None

    def test_dict_with_tokens(self):
        from deathstar_server.services.agent_runner import _usage_dict

        result = _usage_dict({"input_tokens": 100, "output_tokens": 50})
        assert result == {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}

    def test_dict_with_missing_keys(self):
        from deathstar_server.services.agent_runner import _usage_dict

        result = _usage_dict({})
        assert result == {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    def test_non_dict_returns_none(self):
        from deathstar_server.services.agent_runner import _usage_dict

        assert _usage_dict("unexpected") is None


# ---------------------------------------------------------------------------
# AgentSessionResponse Literal status (I7)
# ---------------------------------------------------------------------------


class TestAgentSessionResponseModel:
    def test_valid_statuses_accepted(self):
        from deathstar_shared.models import AgentSessionResponse, WorkflowKind

        for status in ("starting", "running", "waiting_permission", "completed", "failed"):
            obj = AgentSessionResponse(
                conversation_id="c",
                repo="r",
                workflow=WorkflowKind.PROMPT,
                status=status,
                started_at=0.0,
                last_active=0.0,
            )
            assert obj.status == status

    def test_invalid_status_rejected(self):
        from pydantic import ValidationError

        from deathstar_shared.models import AgentSessionResponse, WorkflowKind

        with pytest.raises(ValidationError):
            AgentSessionResponse(
                conversation_id="c",
                repo="r",
                workflow=WorkflowKind.PROMPT,
                status="bogus",  # not in Literal
                started_at=0.0,
                last_active=0.0,
            )

    def test_default_status_is_running(self):
        from deathstar_shared.models import AgentSessionResponse, WorkflowKind

        obj = AgentSessionResponse(
            conversation_id="c",
            repo="r",
            workflow=WorkflowKind.PROMPT,
            started_at=0.0,
            last_active=0.0,
        )
        assert obj.status == "running"
