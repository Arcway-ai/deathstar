from __future__ import annotations

import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from deathstar_server.services.event_bus import (
    EVENT_LINEAR_ISSUE_CREATED,
    EVENT_LINEAR_ISSUE_DELETED,
    EVENT_LINEAR_ISSUE_UPDATED,
    EVENT_LINEAR_PROJECT_UPDATED,
    RepoEvent,
    SOURCE_LINEAR,
)

logger = logging.getLogger(__name__)

linear_webhook_router = APIRouter(prefix="/web/api/webhooks", tags=["webhooks"])


def _verify_signature(secret: str, body: bytes, signature: str) -> bool:
    """Verify Linear's HMAC-SHA256 webhook signature.

    Linear sends the signature in the ``Linear-Signature`` header as a
    raw hex digest (no ``sha256=`` prefix).
    """
    if not signature:
        return False
    expected = hmac.new(
        secret.encode(), body, hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@linear_webhook_router.post("/linear")
async def linear_webhook(request: Request) -> JSONResponse:
    """Receive Linear webhook events (Issue, Project).

    Requires LINEAR_WEBHOOK_SECRET to be configured. The webhook
    self-authenticates via HMAC-SHA256, so this endpoint is public.
    """
    from deathstar_server.app_state import event_bus, linear_store, settings

    secret = settings.linear_webhook_secret
    if not secret:
        return JSONResponse(
            status_code=503,
            content={"detail": "Linear webhook receiver not configured"},
        )

    # Verify signature
    body = await request.body()
    signature = request.headers.get("Linear-Signature", "")
    if not _verify_signature(secret, body, signature):
        logger.warning("linear webhook: invalid signature")
        return JSONResponse(status_code=401, content={"detail": "invalid signature"})

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse(status_code=400, content={"detail": "invalid JSON body"})

    action = payload.get("action", "")
    event_type = payload.get("type", "")
    linear_event = request.headers.get("Linear-Event", "")

    logger.debug(
        "linear webhook: type=%s action=%s event_header=%s",
        event_type, action, linear_event,
    )

    event = _translate_webhook(payload, event_type, action, linear_store)
    if event:
        delivered = event_bus.publish(event)
        logger.info(
            "linear webhook: %s/%s for %s → delivered to %d subscribers",
            event_type,
            action,
            event.repo,
            delivered,
        )
        return JSONResponse(status_code=200, content={"delivered": delivered})

    return JSONResponse(
        status_code=200,
        content={"detail": f"ignored: type={event_type} action={action}"},
    )


def _translate_webhook(
    payload: dict,
    event_type: str,
    action: str,
    linear_store: object,
) -> RepoEvent | None:
    """Translate a Linear webhook payload into a RepoEvent.

    Linear webhook payloads include:
    - ``type``: "Issue" or "Project"
    - ``action``: "create", "update", or "remove"
    - ``data``: the full object (issue or project data)
    - ``organizationId``, ``createdAt``, etc.
    """
    data = payload.get("data", {})
    if not data:
        return None

    if event_type == "Issue":
        return _handle_issue_event(data, action, linear_store)

    if event_type == "Project":
        return _handle_project_event(data, action, linear_store)

    return None


def _handle_issue_event(
    data: dict,
    action: str,
    linear_store: object,
) -> RepoEvent | None:
    """Translate an Issue webhook event into a RepoEvent."""
    # Resolve repo from the project link in our DB
    team_obj = data.get("team", {})
    team_id = team_obj.get("id", "") if isinstance(team_obj, dict) else ""
    project_obj = data.get("project", {})
    project_id = project_obj.get("id", "") if isinstance(project_obj, dict) else ""

    # Try to resolve the repo from our linked project
    repo = _resolve_repo(linear_store, project_id, team_id)
    if not repo:
        logger.debug(
            "linear webhook: ignoring issue event — no linked project "
            "(project_id=%s, team_id=%s)",
            project_id, team_id,
        )
        return None

    state_obj = data.get("state", {})
    status = state_obj.get("name", "") if isinstance(state_obj, dict) else ""
    assignee_obj = data.get("assignee", {})
    assignee = ""
    if isinstance(assignee_obj, dict):
        assignee = assignee_obj.get("displayName") or assignee_obj.get("name", "")

    event_data = {
        "linear_issue_id": data.get("id", ""),
        "identifier": data.get("identifier", ""),
        "title": data.get("title", ""),
        "status": status,
        "priority": data.get("priority", 0),
        "assignee": assignee,
        "url": data.get("url", ""),
        "project_id": project_id,
        "action": action,
    }

    if action == "create":
        event_type_const = EVENT_LINEAR_ISSUE_CREATED
    elif action == "remove":
        event_type_const = EVENT_LINEAR_ISSUE_DELETED
    else:
        event_type_const = EVENT_LINEAR_ISSUE_UPDATED

    return RepoEvent(
        event_type=event_type_const,
        repo=repo,
        source=SOURCE_LINEAR,
        data=event_data,
    )


def _handle_project_event(
    data: dict,
    action: str,
    linear_store: object,
) -> RepoEvent | None:
    """Translate a Project webhook event into a RepoEvent."""
    project_id = data.get("id", "")
    if not project_id:
        return None

    # Look up our linked project to get the repo
    project = linear_store.get_project_by_linear_id(project_id)  # type: ignore[attr-defined]
    if not project:
        logger.debug(
            "linear webhook: ignoring project event — not linked (id=%s)",
            project_id,
        )
        return None

    status_obj = data.get("status", {})
    state_type = ""
    state_name = ""
    if isinstance(status_obj, dict):
        state_type = status_obj.get("type", "")
        state_name = status_obj.get("name", "")

    return RepoEvent(
        event_type=EVENT_LINEAR_PROJECT_UPDATED,
        repo=project.repo,
        source=SOURCE_LINEAR,
        data={
            "linear_project_id": project_id,
            "name": data.get("name", project.name),
            "state_type": state_type,
            "state_name": state_name,
            "action": action,
        },
    )


def _resolve_repo(
    linear_store: object,
    project_id: str,
    team_id: str,
) -> str | None:
    """Resolve a repo name from a Linear project/team ID.

    Tries project_id first (most specific), then falls back to
    checking all projects for the team.
    """
    if project_id:
        project = linear_store.get_project_by_linear_id(project_id)  # type: ignore[attr-defined]
        if project:
            return project.repo
    # Fallback: no direct resolution possible without project_id
    return None
