"""WebSocket agent — thin subscriber that forwards AgentRunner events to the browser."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from deathstar_server.errors import AppError
from deathstar_server.services.agent_runner import AgentEventType, AgentRunner
from deathstar_shared.models import WorkflowKind

logger = logging.getLogger(__name__)

agent_ws_router = APIRouter(prefix="/web/api")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def _authenticate(websocket: WebSocket) -> bool:
    from deathstar_server.app_state import settings as _settings
    if not _settings.api_token:
        return True
    from deathstar_server.session import SESSION_COOKIE_NAME, validate_session_token
    cookie = websocket.cookies.get(SESSION_COOKIE_NAME)
    if cookie and validate_session_token(cookie, _settings.api_token):
        return True
    token = websocket.query_params.get("token")
    if token:
        return hmac.compare_digest(token, _settings.api_token)
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _send(ws: WebSocket, msg_type: str, **data) -> None:
    try:
        await ws.send_json({"type": msg_type, **data})
    except (WebSocketDisconnect, RuntimeError):
        pass


async def _forward_events(ws: WebSocket, repo: str | None) -> None:
    """Subscribe to the event bus and forward repo events to a WebSocket client."""
    from deathstar_server.app_state import event_bus

    try:
        async with event_bus.subscribe(repo) as events:
            async for event in events:
                try:
                    await ws.send_json({
                        "type": "repo_event",
                        "event_type": event.event_type,
                        "repo": event.repo,
                        "source": event.source,
                        "data": event.data,
                        "timestamp": event.timestamp,
                    })
                except (WebSocketDisconnect, RuntimeError):
                    break
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.warning("event forwarding error for repo=%s", repo, exc_info=True)


# Map AgentEventType → WebSocket message type
_EVENT_TO_WS_TYPE = {
    AgentEventType.STARTED: "started",
    AgentEventType.TEXT_DELTA: "text_delta",
    AgentEventType.THINKING_DELTA: "thinking_delta",
    AgentEventType.TOOL_USE: "tool_use",
    AgentEventType.TOOL_RESULT: "tool_result",
    AgentEventType.PERMISSION_REQUEST: "permission_request",
    AgentEventType.RESULT: "result",
    AgentEventType.ERROR: "error",
    AgentEventType.STATUS: "status",
    AgentEventType.COMPACT_DONE: "compact_done",
}


async def _forward_agent_events(
    ws: WebSocket,
    agent_runner: AgentRunner,
    conversation_id: str,
    sub_id: str,
    queue: asyncio.Queue,
) -> None:
    """Read events from an agent's subscriber queue and forward to WebSocket."""
    try:
        while True:
            event = await queue.get()
            ws_type = _EVENT_TO_WS_TYPE.get(event.type, event.type.value)
            try:
                await ws.send_json({"type": ws_type, **event.data})
            except (WebSocketDisconnect, RuntimeError):
                break
    except asyncio.CancelledError:
        pass
    finally:
        agent_runner.unsubscribe(conversation_id, sub_id)


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


@agent_ws_router.websocket("/agent")
async def agent_ws(websocket: WebSocket) -> None:
    """Interactive Claude Code agent session over WebSocket.

    This is a thin subscriber layer. All agent execution happens in AgentRunner.
    The WebSocket subscribes to events from running agents and forwards them
    to the browser. Disconnecting does NOT stop the agent — it keeps running.

    Client-to-server messages:
        {"type": "start", "repo": "...", "message": "...", "workflow": "prompt",
         "conversation_id": "...|null", "model": "...", "system": "...",
         "auto_accept": true|false, "branch": "...", "context_files": [...]}
        {"type": "input", "text": "..."}
        {"type": "permission_response", "allow": true|false}
        {"type": "interrupt"}
        {"type": "compact"}
        {"type": "subscribe_agent", "conversation_id": "..."}
        {"type": "subscribe_events", "repo": "..."}

    Server-to-client messages:
        {"type": "started", "conversation_id": "..."}
        {"type": "text_delta", "text": "..."}
        {"type": "thinking_delta", "text": "..."}
        {"type": "tool_use", "id": "...", "tool": "...", "input": {...}}
        {"type": "tool_result", "tool_use_id": "...", "content": "...", "is_error": false}
        {"type": "permission_request", "tool": "...", "input": {...}}
        {"type": "result", "conversation_id": "...", ...}
        {"type": "status", ...}
        {"type": "error", "code": "...", "message": "..."}
        {"type": "compact_done", "summary": "..."}
        {"type": "agent_snapshot", "status": "...", "text": "...", "blocks": [...]}
    """
    if not _authenticate(websocket):
        await websocket.close(code=4001, reason="unauthorized")
        return

    from deathstar_server.app_state import agent_runner

    await websocket.accept()

    current_conv_id: str | None = None
    current_sub_id: str | None = None
    agent_forward_task: asyncio.Task | None = None
    event_forward_task: asyncio.Task | None = None

    def _unsubscribe_agent() -> None:
        """Clean up agent subscription without stopping the agent."""
        nonlocal current_sub_id, agent_forward_task
        if agent_forward_task:
            agent_forward_task.cancel()
            agent_forward_task = None
        if current_conv_id and current_sub_id:
            agent_runner.unsubscribe(current_conv_id, current_sub_id)
            current_sub_id = None

    async def _subscribe_to_agent(conversation_id: str) -> None:
        """Subscribe to an agent's event stream and start forwarding."""
        nonlocal current_conv_id, current_sub_id, agent_forward_task

        # Unsubscribe from previous agent
        _unsubscribe_agent()

        current_conv_id = conversation_id
        result = agent_runner.subscribe(conversation_id)
        if not result:
            return
        sub_id, queue = result
        current_sub_id = sub_id
        agent_forward_task = asyncio.create_task(
            _forward_agent_events(websocket, agent_runner, conversation_id, sub_id, queue),
            name=f"ws-forward-{conversation_id[:8]}",
        )

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send(websocket, "error", code="INVALID_JSON", message="invalid JSON")
                continue

            msg_type = msg.get("type")

            if msg_type == "start":
                await _handle_start(websocket, msg, agent_runner, _subscribe_to_agent)

            elif msg_type == "input" and current_conv_id:
                try:
                    follow_up = msg.get("text", "")
                    await agent_runner.send_followup(current_conv_id, follow_up)
                    # Re-subscribe since send_followup resets accumulated state
                    await _subscribe_to_agent(current_conv_id)
                except AppError as exc:
                    await _send(websocket, "error", code="INTERNAL_ERROR", message=exc.message)
                except Exception as exc:
                    await _send(websocket, "error", code="INTERNAL_ERROR", message=str(exc))

            elif msg_type == "permission_response" and current_conv_id:
                allow = msg.get("allow", False)
                agent_runner.respond_permission(current_conv_id, allow)

            elif msg_type == "compact" and current_conv_id:
                try:
                    await agent_runner.compact(current_conv_id)
                except Exception as exc:
                    logger.warning("compact failed: %s", exc)
                    await _send(websocket, "compact_done", summary="Compact failed")

            elif msg_type == "interrupt" and current_conv_id:
                await agent_runner.interrupt(current_conv_id)

            elif msg_type == "subscribe_agent":
                # Reconnect: subscribe to an already-running agent
                conversation_id = msg.get("conversation_id")
                if not conversation_id:
                    await _send(websocket, "error", code="INVALID_REQUEST", message="conversation_id required")
                    continue
                agent = agent_runner.get_agent(conversation_id)
                if not agent:
                    await _send(websocket, "error", code="NOT_FOUND", message="No agent for this conversation")
                    continue
                await _subscribe_to_agent(conversation_id)
                # Send snapshot so reconnecting client catches up
                await _send(websocket, "agent_snapshot", **agent.get_snapshot())

            elif msg_type == "subscribe_events":
                repo = msg.get("repo")
                if not repo:
                    await _send(websocket, "error", code="INVALID_REQUEST", message="repo is required")
                    continue
                if event_forward_task:
                    event_forward_task.cancel()
                event_forward_task = asyncio.create_task(
                    _forward_events(websocket, repo),
                    name="event-forward",
                )

            else:
                await _send(websocket, "error", code="UNKNOWN_MESSAGE", message=f"unknown message type: {msg_type}")

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("agent_ws error")
    finally:
        # Clean up subscriptions — agent keeps running
        _unsubscribe_agent()
        if event_forward_task:
            event_forward_task.cancel()


async def _handle_start(
    websocket: WebSocket,
    msg: dict,
    agent_runner: AgentRunner,
    subscribe_fn,
) -> None:
    """Handle a 'start' message — delegate to AgentRunner."""
    repo = msg.get("repo", "")
    message = msg.get("message", "")
    workflow_str = msg.get("workflow", "prompt")
    conversation_id = msg.get("conversation_id")
    model = msg.get("model")
    system_prompt = msg.get("system")
    auto_accept = msg.get("auto_accept", False)
    branch = msg.get("branch") or None
    context_files: list[str] = msg.get("context_files") or []

    try:
        workflow = WorkflowKind(workflow_str)
    except ValueError:
        workflow = WorkflowKind.PROMPT

    logger.info(
        "agent start: repo=%s branch=%s workflow=%s conv=%s model=%s",
        repo, branch, workflow_str, conversation_id, model,
    )

    try:
        agent = await agent_runner.start_agent(
            conversation_id=conversation_id,
            repo=repo,
            branch=branch,
            message=message,
            workflow=workflow,
            model=model,
            system_prompt=system_prompt,
            auto_accept=auto_accept,
            context_files=context_files,
        )
        # Subscribe to the agent's event stream
        await subscribe_fn(agent.conversation_id)
    except AppError as exc:
        error_code = getattr(exc, "code", "INTERNAL_ERROR")
        if isinstance(error_code, str):
            pass
        else:
            error_code = error_code.value if hasattr(error_code, "value") else str(error_code)
        await _send(websocket, "error", code=error_code, message=exc.message)
    except Exception as exc:
        logger.exception("start_agent failed: %s", exc)
        await _send(websocket, "error", code="INTERNAL_ERROR", message=str(exc))
