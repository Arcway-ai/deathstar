from __future__ import annotations

import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from deathstar_server.services.event_bus import (
    EVENT_CI_STATUS,
    EVENT_PR_UPDATE,
    EVENT_PUSH,
    RepoEvent,
    SOURCE_GITHUB,
)

logger = logging.getLogger(__name__)

webhook_router = APIRouter(prefix="/web/api/webhooks", tags=["webhooks"])


def _verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify GitHub HMAC-SHA256 webhook signature."""
    if not signature.startswith("sha256="):
        return False
    expected = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)


def _repo_name_from_payload(payload: dict) -> str | None:
    """Extract the repo name from a GitHub webhook payload."""
    repo = payload.get("repository", {})
    return repo.get("name") if repo else None


@webhook_router.post("/github")
async def github_webhook(request: Request) -> JSONResponse:
    """Receive GitHub webhook events (push, PR, status).

    Requires GITHUB_WEBHOOK_SECRET to be configured. The webhook
    self-authenticates via HMAC-SHA256, so this endpoint is public.
    """
    from deathstar_server.app_state import event_bus, settings

    secret = settings.github_webhook_secret
    if not secret:
        return JSONResponse(
            status_code=503,
            content={"detail": "webhook receiver not configured"},
        )

    # Verify signature
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not _verify_signature(body, signature, secret):
        logger.warning("webhook: invalid signature")
        return JSONResponse(status_code=401, content={"detail": "invalid signature"})

    gh_event = request.headers.get("X-GitHub-Event", "")
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse(status_code=400, content={"detail": "invalid JSON body"})

    repo_name = _repo_name_from_payload(payload)
    if not repo_name:
        return JSONResponse(status_code=200, content={"detail": "ignored (no repo)"})

    event = _translate_webhook(gh_event, repo_name, payload)
    if event:
        delivered = event_bus.publish(event)
        logger.info(
            "webhook: %s for %s → delivered to %d subscribers",
            gh_event,
            repo_name,
            delivered,
        )
        return JSONResponse(status_code=200, content={"delivered": delivered})

    return JSONResponse(status_code=200, content={"detail": f"ignored event type: {gh_event}"})


def _translate_webhook(gh_event: str, repo_name: str, payload: dict) -> RepoEvent | None:
    """Translate a GitHub webhook payload into a RepoEvent."""
    sender = payload.get("sender", {}).get("login", "unknown")

    if gh_event == "push":
        commits = []
        for c in payload.get("commits", [])[:10]:
            commits.append({
                "sha": c.get("id", "")[:7],
                "message": c.get("message", "").split("\n")[0][:100],
                "author": c.get("author", {}).get("name", "unknown"),
            })
        return RepoEvent(
            event_type=EVENT_PUSH,
            repo=repo_name,
            source=SOURCE_GITHUB,
            data={
                "ref": payload.get("ref", ""),
                "commits": commits,
                "sender": sender,
            },
        )

    if gh_event == "pull_request":
        pr = payload.get("pull_request", {})
        return RepoEvent(
            event_type=EVENT_PR_UPDATE,
            repo=repo_name,
            source=SOURCE_GITHUB,
            data={
                "action": payload.get("action", ""),
                "number": pr.get("number"),
                "title": pr.get("title", ""),
                "state": pr.get("state", ""),
                "head_branch": pr.get("head", {}).get("ref", ""),
                "sender": sender,
            },
        )

    if gh_event == "status":
        return RepoEvent(
            event_type=EVENT_CI_STATUS,
            repo=repo_name,
            source=SOURCE_GITHUB,
            data={
                "sha": payload.get("sha", "")[:7],
                "state": payload.get("state", ""),
                "context": payload.get("context", ""),
                "target_url": payload.get("target_url", ""),
            },
        )

    return None
