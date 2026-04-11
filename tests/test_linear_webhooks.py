from __future__ import annotations

import hashlib
import hmac
from unittest.mock import MagicMock

from deathstar_server.services.event_bus import (
    EVENT_LINEAR_ISSUE_CREATED,
    EVENT_LINEAR_ISSUE_DELETED,
    EVENT_LINEAR_ISSUE_UPDATED,
    EVENT_LINEAR_PROJECT_UPDATED,
)
from deathstar_server.web.linear_webhooks import (
    _handle_issue_event,
    _handle_project_event,
    _translate_webhook,
    _verify_signature,
)


# ------------------------------------------------------------------
# Signature verification
# ------------------------------------------------------------------


class TestVerifySignature:
    def test_valid_signature(self) -> None:
        secret = "whsec_test123"
        body = b'{"type":"Issue","action":"create"}'
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert _verify_signature(secret, body, sig) is True

    def test_invalid_signature(self) -> None:
        secret = "whsec_test123"
        body = b'{"type":"Issue","action":"create"}'
        assert _verify_signature(secret, body, "bad_signature") is False

    def test_empty_signature(self) -> None:
        assert _verify_signature("secret", b"body", "") is False

    def test_tampered_body(self) -> None:
        secret = "whsec_test123"
        body = b'{"type":"Issue","action":"create"}'
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert _verify_signature(secret, b"tampered", sig) is False


# ------------------------------------------------------------------
# Issue event translation
# ------------------------------------------------------------------


def _mock_store_with_project(repo: str = "my-repo") -> MagicMock:
    """Return a mock LinearStore that resolves project lookups."""
    store = MagicMock()
    project = MagicMock()
    project.repo = repo
    project.name = "Test Project"
    store.get_project_by_linear_id.return_value = project
    return store


def _mock_store_unlinked() -> MagicMock:
    """Return a mock LinearStore with no linked projects."""
    store = MagicMock()
    store.get_project_by_linear_id.return_value = None
    return store


class TestHandleIssueEvent:
    def test_create_event(self) -> None:
        store = _mock_store_with_project()
        data = {
            "id": "issue-1",
            "identifier": "ENG-42",
            "title": "Add login page",
            "state": {"name": "Todo"},
            "priority": 2,
            "url": "https://linear.app/issue/1",
            "team": {"id": "team-1"},
            "project": {"id": "proj-1"},
            "assignee": {"displayName": "Alice"},
        }
        event = _handle_issue_event(data, "create", store)
        assert event is not None
        assert event.event_type == EVENT_LINEAR_ISSUE_CREATED
        assert event.repo == "my-repo"
        assert event.data["identifier"] == "ENG-42"
        assert event.data["assignee"] == "Alice"
        assert event.data["action"] == "create"

    def test_update_event(self) -> None:
        store = _mock_store_with_project()
        data = {
            "id": "issue-1",
            "identifier": "ENG-42",
            "title": "Updated",
            "state": {"name": "In Progress"},
            "priority": 1,
            "url": "",
            "team": {"id": "t1"},
            "project": {"id": "proj-1"},
        }
        event = _handle_issue_event(data, "update", store)
        assert event is not None
        assert event.event_type == EVENT_LINEAR_ISSUE_UPDATED
        assert event.data["status"] == "In Progress"

    def test_remove_event(self) -> None:
        store = _mock_store_with_project()
        data = {
            "id": "issue-1",
            "identifier": "ENG-42",
            "title": "Deleted",
            "state": {"name": "Cancelled"},
            "priority": 0,
            "url": "",
            "team": {"id": "t1"},
            "project": {"id": "proj-1"},
        }
        event = _handle_issue_event(data, "remove", store)
        assert event is not None
        assert event.event_type == EVENT_LINEAR_ISSUE_DELETED

    def test_unlinked_project_returns_none(self) -> None:
        store = _mock_store_unlinked()
        data = {
            "id": "issue-1",
            "identifier": "ENG-1",
            "title": "Task",
            "state": {"name": "Todo"},
            "team": {"id": "unknown-team"},
            "project": {"id": "unknown-proj"},
        }
        event = _handle_issue_event(data, "create", store)
        assert event is None

    def test_missing_team_and_project(self) -> None:
        store = _mock_store_unlinked()
        data = {
            "id": "issue-1",
            "identifier": "ENG-1",
            "title": "Task",
            "state": {"name": "Todo"},
        }
        event = _handle_issue_event(data, "create", store)
        assert event is None

    def test_assignee_fallback_to_name(self) -> None:
        store = _mock_store_with_project()
        data = {
            "id": "issue-1",
            "identifier": "ENG-1",
            "title": "Task",
            "state": {"name": "Todo"},
            "team": {"id": "t1"},
            "project": {"id": "p1"},
            "assignee": {"name": "bob"},
        }
        event = _handle_issue_event(data, "create", store)
        assert event is not None
        assert event.data["assignee"] == "bob"


# ------------------------------------------------------------------
# Project event translation
# ------------------------------------------------------------------


class TestHandleProjectEvent:
    def test_update_event(self) -> None:
        store = _mock_store_with_project()
        data = {
            "id": "proj-1",
            "name": "Sprint 1 (updated)",
            "status": {"type": "started", "name": "Started"},
        }
        event = _handle_project_event(data, "update", store)
        assert event is not None
        assert event.event_type == EVENT_LINEAR_PROJECT_UPDATED
        assert event.repo == "my-repo"
        assert event.data["name"] == "Sprint 1 (updated)"
        assert event.data["state_type"] == "started"
        assert event.data["state_name"] == "Started"

    def test_unlinked_project_returns_none(self) -> None:
        store = _mock_store_unlinked()
        data = {"id": "not-linked"}
        event = _handle_project_event(data, "update", store)
        assert event is None

    def test_missing_id_returns_none(self) -> None:
        store = _mock_store_with_project()
        data = {"name": "No ID"}
        event = _handle_project_event(data, "update", store)
        assert event is None

    def test_missing_status_object(self) -> None:
        store = _mock_store_with_project()
        data = {"id": "proj-1", "name": "P"}
        event = _handle_project_event(data, "update", store)
        assert event is not None
        assert event.data["state_type"] == ""
        assert event.data["state_name"] == ""


# ------------------------------------------------------------------
# Top-level translate_webhook dispatch
# ------------------------------------------------------------------


class TestTranslateWebhook:
    def test_dispatches_issue_event(self) -> None:
        store = _mock_store_with_project()
        payload = {
            "type": "Issue",
            "action": "create",
            "data": {
                "id": "i1",
                "identifier": "ENG-1",
                "title": "Task",
                "state": {"name": "Todo"},
                "team": {"id": "t1"},
                "project": {"id": "p1"},
            },
        }
        event = _translate_webhook(payload, "Issue", "create", store)
        assert event is not None
        assert event.event_type == EVENT_LINEAR_ISSUE_CREATED

    def test_dispatches_project_event(self) -> None:
        store = _mock_store_with_project()
        payload = {
            "type": "Project",
            "action": "update",
            "data": {"id": "proj-1", "name": "P"},
        }
        event = _translate_webhook(payload, "Project", "update", store)
        assert event is not None
        assert event.event_type == EVENT_LINEAR_PROJECT_UPDATED

    def test_unknown_type_returns_none(self) -> None:
        store = _mock_store_with_project()
        payload = {"type": "Comment", "action": "create", "data": {"id": "c1"}}
        event = _translate_webhook(payload, "Comment", "create", store)
        assert event is None

    def test_empty_data_returns_none(self) -> None:
        store = _mock_store_with_project()
        payload = {"type": "Issue", "action": "create", "data": {}}
        event = _translate_webhook(payload, "Issue", "create", store)
        assert event is None

    def test_missing_data_key_returns_none(self) -> None:
        store = _mock_store_with_project()
        payload = {"type": "Issue", "action": "create"}
        event = _translate_webhook(payload, "Issue", "create", store)
        assert event is None
