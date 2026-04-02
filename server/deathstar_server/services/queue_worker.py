"""Background worker that processes queued agent messages."""

from __future__ import annotations

import asyncio
import logging
import time

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeSDKClient,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from claude_agent_sdk.types import (
    PermissionResultAllow,
    ThinkingBlock,
)

from deathstar_server.services.event_bus import (
    EVENT_QUEUE_COMPLETED,
    EVENT_QUEUE_FAILED,
    EventBus,
    RepoEvent,
    SOURCE_LOCAL,
)
from deathstar_server.web.agent_ws import (
    _build_options,
    _check_claude_auth,
    _check_protected_branch_push,
    _ensure_claudeignore,
    _usage_dict,
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
    ) -> None:
        self._queue_store = queue_store
        self._conversation_store = conversation_store
        self._worktree_manager = worktree_manager
        self._event_bus = event_bus
        self._task: asyncio.Task | None = None
        self._running = False
        self._wake_event = asyncio.Event()
        self._poll_interval = 3
        # Interrupt support: track the item currently being executed.
        # _loop is captured in start() so interrupt_if_current() — which is
        # called from a sync FastAPI threadpool handler — can schedule the
        # coroutine onto the correct event loop via run_coroutine_threadsafe.
        self._current_item_id: str | None = None
        self._current_client: ClaudeSDKClient | None = None
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
        """Interrupt the SDK client if item_id is the one currently executing.

        Called synchronously from the HTTP cancel route (which runs in a
        ThreadPoolExecutor, not the event loop thread).  We use
        run_coroutine_threadsafe so the interrupt coroutine is scheduled onto
        the correct event loop rather than the calling thread's loop (which
        does not exist in Python 3.12).
        """
        if self._current_item_id == item_id and self._current_client is not None:
            if self._loop is None or not self._loop.is_running():
                logger.warning(
                    "cannot interrupt queue item %s: event loop not available", item_id
                )
                return
            logger.info("interrupting queue item %s on cancel request", item_id)
            asyncio.run_coroutine_threadsafe(
                self._current_client.interrupt(), self._loop
            )

    async def _process_loop(self) -> None:
        recovered = self._queue_store.recover_stale()
        if recovered:
            logger.info("recovered %d stale queue items on startup", recovered)

        last_recovery = time.time()

        while self._running:
            try:
                # Periodic stale-item recovery (catches items stuck in
                # 'processing' after a crash or unclean shutdown).
                if time.time() - last_recovery >= _STALE_RECOVERY_INTERVAL:
                    recovered = self._queue_store.recover_stale()
                    if recovered:
                        logger.info("periodic recovery: reset %d stale items", recovered)
                    last_recovery = time.time()

                processed = await self._process_one()
                if not processed:
                    try:
                        await asyncio.wait_for(
                            self._wake_event.wait(),
                            timeout=self._poll_interval,
                        )
                    except asyncio.TimeoutError:
                        pass
                    self._wake_event.clear()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("queue worker error")
                await asyncio.sleep(5)

    def _active_branches(self) -> set[tuple[str, str | None]]:
        """Return the set of (repo, branch) pairs with active WebSocket sessions."""
        from deathstar_server.web.agent_ws import get_active_branches
        return {
            (repo, branch)
            for (repo, branch) in get_active_branches()
        }

    async def _process_one(self) -> bool:
        # Skip branches with active interactive sessions
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

        # Check auth before doing anything
        if not _check_claude_auth():
            raise RuntimeError("Claude is not authenticated")

        # Resolve working directory
        cwd = self._worktree_manager.resolve_working_dir(repo, branch_str)
        _ensure_claudeignore(cwd)

        # Add user message to conversation
        self._conversation_store.add_user_message(conversation_id, message)

        # Look up session for multi-turn continuity
        sdk_session_id = self._conversation_store.get_session_id(conversation_id)

        # Build auto-accept permission callback
        async def auto_accept_tool(tool_name, tool_input, context):
            deny = _check_protected_branch_push(tool_name, tool_input)
            if deny:
                return deny
            return PermissionResultAllow()

        options = _build_options(
            workflow=workflow,
            cwd=str(cwd),
            system_prompt=system_str,
            model=model_str,
            session_id=sdk_session_id,
            can_use_tool=auto_accept_tool,
        )

        client = ClaudeSDKClient(options=options)
        self._current_item_id = item_id
        self._current_client = client
        try:
            await client.connect()
            await client.query(message)

            # Read all messages — same pattern as _read_messages in agent_ws.py
            started = time.perf_counter()
            accumulated_text = ""
            accumulated_blocks: list[dict] = []
            result_received = False

            async for msg in client.receive_messages():
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            if block.text not in accumulated_text:
                                accumulated_text += block.text
                            if accumulated_blocks and accumulated_blocks[-1].get("type") == "text":
                                if block.text not in accumulated_blocks[-1]["text"]:
                                    accumulated_blocks[-1]["text"] += block.text
                            else:
                                if not any(
                                    b.get("type") == "text" and block.text in b["text"]
                                    for b in accumulated_blocks
                                ):
                                    accumulated_blocks.append({"type": "text", "text": block.text})
                        elif isinstance(block, ToolUseBlock):
                            accumulated_blocks.append({
                                "type": "tool_use", "id": block.id,
                                "tool": block.name, "input": block.input,
                            })
                        elif isinstance(block, ToolResultBlock):
                            content = block.content
                            if isinstance(content, list):
                                content = "\n".join(
                                    item.get("text", str(item))
                                    for item in content
                                    if isinstance(item, dict)
                                )
                            accumulated_blocks.append({
                                "type": "tool_result",
                                "toolUseId": block.tool_use_id,
                                "content": str(content or "")[:2000],
                                "isError": block.is_error or False,
                            })
                        elif isinstance(block, ThinkingBlock):
                            if accumulated_blocks and accumulated_blocks[-1].get("type") == "thinking":
                                accumulated_blocks[-1]["text"] += block.thinking
                            else:
                                accumulated_blocks.append({"type": "thinking", "text": block.thinking})

                elif isinstance(msg, StreamEvent):
                    event_data = msg.event
                    if event_data.get("type") == "content_block_delta":
                        delta = event_data.get("delta", {})
                        if delta.get("type") == "text_delta":
                            text = delta.get("text", "")
                            if text:
                                accumulated_text += text
                                if accumulated_blocks and accumulated_blocks[-1].get("type") == "text":
                                    accumulated_blocks[-1]["text"] += text
                                else:
                                    accumulated_blocks.append({"type": "text", "text": text})
                        elif delta.get("type") == "thinking_delta":
                            text = delta.get("thinking", "")
                            if text:
                                if accumulated_blocks and accumulated_blocks[-1].get("type") == "thinking":
                                    accumulated_blocks[-1]["text"] += text
                                else:
                                    accumulated_blocks.append({"type": "thinking", "text": text})

                elif isinstance(msg, ResultMessage):
                    result_received = True
                    duration_ms = int((time.perf_counter() - started) * 1000)
                    final_text = accumulated_text or msg.result or ""

                    # Handle stale sessions
                    if msg.is_error and duration_ms < 5000 and (msg.num_turns or 0) <= 1:
                        logger.warning(
                            "queue: resumed session failed quickly — clearing session_id for conv=%s",
                            conversation_id,
                        )
                        self._conversation_store.update_session_id(conversation_id, None)
                    elif msg.session_id:
                        self._conversation_store.update_session_id(
                            conversation_id, msg.session_id,
                        )

                    # Save assistant message
                    msg_id = self._conversation_store.add_assistant_message(
                        conversation_id,
                        final_text,
                        workflow=workflow,
                        provider="anthropic",
                        model="claude",
                        duration_ms=duration_ms,
                        agent_blocks=accumulated_blocks or None,
                    )

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
                            "usage": _usage_dict(msg.usage),
                        },
                    ))

                    logger.info(
                        "queue item %s completed: conv=%s msg=%s duration=%dms",
                        item_id, conversation_id, msg_id, duration_ms,
                    )
                    break

            if not result_received:
                raise RuntimeError("SDK stream ended without producing a ResultMessage")

        finally:
            # Clear current-item tracking so interrupt_if_current is a no-op
            # once this item has finished (success, failure, or cancel).
            if self._current_item_id == item_id:
                self._current_item_id = None
                self._current_client = None
            try:
                await client.disconnect()
            except Exception:
                logger.warning("failed to disconnect SDK client for queue item %s", item_id, exc_info=True)
