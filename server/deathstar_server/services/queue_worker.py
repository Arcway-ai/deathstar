"""Background worker that processes queued agent messages via AgentRunner."""

from __future__ import annotations

import asyncio
import logging
import time

from deathstar_server.services.agent_runner import (
    AgentEvent,
    AgentEventType,
    AgentRunner,
)
from deathstar_server.services.event_bus import (
    EVENT_QUEUE_COMPLETED,
    EVENT_QUEUE_FAILED,
    EVENT_QUEUE_PROCESSING,
    EventBus,
    RepoEvent,
    SOURCE_LOCAL,
)
from deathstar_server.web.conversations import ConversationStore
from deathstar_server.web.queue_store import QueueStore
from deathstar_server.services.worktree import WorktreeManager
from deathstar_shared.models import WorkflowKind

logger = logging.getLogger(__name__)


_STALE_RECOVERY_INTERVAL = 300  # seconds between periodic stale-item sweeps


class QueueWorker:
    """Background asyncio task that processes queued agent messages."""

    def __init__(
        self,
        queue_store: QueueStore,
        conversation_store: ConversationStore,
        worktree_manager: WorktreeManager,
        event_bus: EventBus,
        agent_runner: AgentRunner,
    ) -> None:
        self._queue_store = queue_store
        self._conversation_store = conversation_store
        self._worktree_manager = worktree_manager
        self._event_bus = event_bus
        self._agent_runner = agent_runner
        self._task: asyncio.Task | None = None
        self._running = False
        self._wake_event: asyncio.Event = asyncio.Event()
        self._poll_interval = 3
        # Track the conversation_id of the currently executing queue item
        # so we can interrupt it via the AgentRunner.
        self._current_item_id: str | None = None
        self._current_conversation_id: str | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.create_task(self._process_loop(), name="queue-worker")
        logger.info("queue worker started")

    async def stop(self) -> None:
        self._running = False
        self._wake_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("queue worker stopped")

    def notify(self) -> None:
        """Wake the worker immediately (call after enqueue)."""
        self._wake_event.set()

    def interrupt_if_current(self, item_id: str) -> None:
        """Interrupt the agent if item_id is the one currently executing."""
        if self._current_item_id != item_id:
            return
        conv_id = self._current_conversation_id
        if not conv_id:
            return
        self._agent_runner.interrupt_threadsafe(conv_id)

    async def _process_loop(self) -> None:
        recovered = self._queue_store.recover_stale()
        if recovered:
            logger.info("recovered %d stale queue items on startup", recovered)

        last_recovery = time.time()

        while self._running:
            try:
                if time.time() - last_recovery >= _STALE_RECOVERY_INTERVAL:
                    recovered = self._queue_store.recover_stale()
                    if recovered:
                        logger.info("periodic recovery: reset %d stale items", recovered)
                    last_recovery = time.time()

                processed = await self._process_one()
                if not processed:
                    # Swap the event before waiting so any notify() call during
                    # the wait goes to the new event — no race window where a
                    # notification can be lost between clear and wait.
                    current_event = self._wake_event
                    self._wake_event = asyncio.Event()
                    try:
                        await asyncio.wait_for(current_event.wait(), timeout=float(self._poll_interval))
                    except asyncio.TimeoutError:
                        pass
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("queue worker error")
                await asyncio.sleep(5)

    def _active_branches(self) -> set[tuple[str, str | None]]:
        """Return the set of (repo, branch) pairs with active agent sessions."""
        return {
            (repo, branch)
            for (repo, branch) in self._agent_runner.get_active_branches()
        }

    async def _process_one(self) -> bool:
        skip = self._active_branches()
        item = self._queue_store.claim_next(skip_repos_branches=skip if skip else None)
        if not item:
            return False

        repo = str(item["repo"])

        try:
            await self._execute_item(item)
        except Exception as exc:
            logger.exception("queue item %s failed", item["id"])
            self._queue_store.mark_failed(str(item["id"]), str(exc)[:2000])
            self._event_bus.publish(RepoEvent(
                event_type=EVENT_QUEUE_FAILED,
                repo=repo,
                source=SOURCE_LOCAL,
                data={
                    "queue_item_id": str(item["id"]),
                    "conversation_id": str(item["conversation_id"]),
                    "error": str(exc)[:200],
                },
            ))
        return True

    async def _execute_item(self, item: dict) -> None:
        """Execute a queue item by delegating to AgentRunner."""
        item_id = str(item["id"])
        conversation_id = str(item["conversation_id"])
        repo = str(item["repo"])
        branch = item.get("branch")
        branch_str = str(branch) if branch else None
        message = str(item["message"])
        workflow_str = str(item.get("workflow", "prompt"))
        model = item.get("model")
        model_str = str(model) if model else None
        system_prompt = item.get("system_prompt")
        system_str = str(system_prompt) if system_prompt else None

        try:
            workflow = WorkflowKind(workflow_str)
        except ValueError:
            workflow = WorkflowKind.PROMPT

        logger.info(
            "processing queue item %s: repo=%s branch=%s conv=%s",
            item_id, repo, branch_str, conversation_id,
        )

        self._current_item_id = item_id
        self._current_conversation_id = conversation_id

        try:
            # Start agent with auto_accept=True (queue items don't have interactive permission flow)
            await self._agent_runner.start_agent(
                conversation_id=conversation_id,
                repo=repo,
                branch=branch_str,
                message=message,
                workflow=workflow,
                model=model_str,
                system_prompt=system_str,
                auto_accept=True,
            )

            # Subscribe immediately after start_agent. The execution task was spawned via
            # asyncio.create_task() and won't run until we yield, so no RESULT event can
            # be published before we subscribe.
            result = self._agent_runner.subscribe(conversation_id)
            if not result:
                raise RuntimeError("Failed to subscribe to agent")
            sub_id, recv_stream = result

            # Notify the frontend now that the agent is registered and
            # subscribable.  The frontend uses conversation_id to auto-
            # subscribe to the agent stream for live text/tool/thinking
            # deltas and to post the queued user message into the chat.
            self._event_bus.publish(RepoEvent(
                event_type=EVENT_QUEUE_PROCESSING,
                repo=repo,
                source=SOURCE_LOCAL,
                data={
                    "queue_item_id": item_id,
                    "conversation_id": conversation_id,
                    "message": message,
                    "workflow": workflow_str,
                },
            ))

            result_event: AgentEvent | None = None
            try:
                async with asyncio.timeout(600):
                    async for event in recv_stream:
                        if event.type == AgentEventType.RESULT:
                            result_event = event
                            break
                        elif event.type == AgentEventType.ERROR:
                            raise RuntimeError(event.data.get("message", "Agent error"))
            except TimeoutError:
                raise RuntimeError("Agent execution timed out (600s)")
            finally:
                self._agent_runner.unsubscribe(conversation_id, sub_id)

            if not result_event:
                raise RuntimeError("Agent completed without producing a result")

            # Mark queue item completed
            msg_id = result_event.data.get("message_id", "")
            duration_ms = result_event.data.get("duration_ms", 0)
            usage = result_event.data.get("usage")

            self._queue_store.mark_completed(item_id, msg_id)

            self._event_bus.publish(RepoEvent(
                event_type=EVENT_QUEUE_COMPLETED,
                repo=repo,
                source=SOURCE_LOCAL,
                data={
                    "queue_item_id": item_id,
                    "conversation_id": conversation_id,
                    "message_id": msg_id,
                    "message_preview": message[:80],
                    "duration_ms": duration_ms,
                    "usage": usage,
                },
            ))

            logger.info(
                "queue item %s completed: conv=%s msg=%s duration=%dms",
                item_id, conversation_id, msg_id, duration_ms,
            )

        finally:
            if self._current_item_id == item_id:
                self._current_item_id = None
                self._current_conversation_id = None
