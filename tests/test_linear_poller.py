from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlmodel import SQLModel

from deathstar_server.db.engine import create_db_engine
from deathstar_server.services.event_bus import (
    EVENT_LINEAR_ISSUE_CREATED,
    EVENT_LINEAR_ISSUE_DELETED,
    EVENT_LINEAR_ISSUE_UPDATED,
    EventBus,
)
from deathstar_server.services.linear import LinearService
from deathstar_server.services.linear_poller import LinearPoller
from deathstar_server.web.linear_store import LinearStore


@pytest.fixture
def settings() -> MagicMock:
    s = MagicMock()
    s.linear_api_key = "lin_test_key"
    s.linear_poll_interval_seconds = 60
    return s


@pytest.fixture
def settings_no_key() -> MagicMock:
    s = MagicMock()
    s.linear_api_key = None
    s.linear_poll_interval_seconds = 60
    return s


@pytest.fixture
def linear_service() -> MagicMock:
    return MagicMock(spec=LinearService)


@pytest.fixture
def store(tmp_path: Path) -> LinearStore:
    engine = create_db_engine(f"sqlite:///{tmp_path}/test.db")
    SQLModel.metadata.create_all(engine)
    return LinearStore(engine)


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


# ------------------------------------------------------------------
# Start / stop lifecycle
# ------------------------------------------------------------------


class TestPollerLifecycle:
    @pytest.mark.asyncio
    async def test_start_disabled_without_api_key(
        self, settings_no_key, linear_service, store, event_bus,
    ) -> None:
        poller = LinearPoller(settings_no_key, linear_service, store, event_bus)
        await poller.start()
        assert poller._running is False
        assert poller._task is None

    @pytest.mark.asyncio
    async def test_start_creates_task(
        self, settings, linear_service, store, event_bus,
    ) -> None:
        poller = LinearPoller(settings, linear_service, store, event_bus)
        await poller.start()
        assert poller._running is True
        assert poller._task is not None
        await poller.stop()
        assert poller._running is False
        assert poller._task is None

    @pytest.mark.asyncio
    async def test_start_idempotent(
        self, settings, linear_service, store, event_bus,
    ) -> None:
        poller = LinearPoller(settings, linear_service, store, event_bus)
        await poller.start()
        task1 = poller._task
        await poller.start()  # second call should be no-op
        assert poller._task is task1
        await poller.stop()


# ------------------------------------------------------------------
# Poll logic
# ------------------------------------------------------------------


class TestPollAllProjects:
    @pytest.mark.asyncio
    async def test_no_linked_projects(
        self, settings, linear_service, store, event_bus,
    ) -> None:
        """No projects in the DB — poll should be a no-op."""
        poller = LinearPoller(settings, linear_service, store, event_bus)
        await poller._poll_all_projects()
        # list_project_issues should never be called
        linear_service.list_project_issues.assert_not_called()

    @pytest.mark.asyncio
    async def test_polls_linked_project(
        self, settings, linear_service, store, event_bus,
    ) -> None:
        """Should fetch issues and sync for a linked project."""
        # Set up a linked project
        store.link_project(
            repo="my-repo",
            linear_project_id="proj-1",
            conversation_id=None,
            team_id="team-1",
            project_data={"name": "Sprint 1", "status": {"type": "started"}},
        )

        # Mock the Linear API to return some issues
        linear_service.list_project_issues = AsyncMock(return_value=[
            {
                "id": "i1", "identifier": "ENG-1", "title": "Task 1",
                "state": {"name": "Todo"}, "priority": 1, "url": "",
            },
        ])

        poller = LinearPoller(settings, linear_service, store, event_bus)
        await poller._poll_all_projects()

        linear_service.list_project_issues.assert_called_once_with("proj-1")

        # Check that the issue was synced to the store
        issue = store.get_issue_by_linear_id("i1")
        assert issue is not None
        assert issue.title == "Task 1"


class TestPublishSyncEvents:
    @pytest.mark.asyncio
    async def test_publishes_created_events(
        self, settings, linear_service, store, event_bus,
    ) -> None:
        store.link_project(
            repo="my-repo",
            linear_project_id="proj-1",
            conversation_id=None,
            team_id="t1",
            project_data={"name": "P", "status": {"type": "started"}},
        )

        issues = [
            {"id": "i1", "identifier": "ENG-1", "title": "New", "state": {"name": "Todo"}, "priority": 0, "url": ""},
        ]
        linear_service.list_project_issues = AsyncMock(return_value=issues)

        published: list = []
        original_publish = event_bus.publish

        def capture_publish(event):
            published.append(event)
            return original_publish(event)

        event_bus.publish = capture_publish

        poller = LinearPoller(settings, linear_service, store, event_bus)
        await poller._poll_all_projects()

        assert len(published) == 1
        assert published[0].event_type == EVENT_LINEAR_ISSUE_CREATED
        assert published[0].repo == "my-repo"

    @pytest.mark.asyncio
    async def test_publishes_updated_events(
        self, settings, linear_service, store, event_bus,
    ) -> None:
        project = store.link_project(
            repo="my-repo",
            linear_project_id="proj-1",
            conversation_id=None,
            team_id="t1",
            project_data={"name": "P", "status": {"type": "started"}},
        )

        # First sync — creates issues
        store.sync_issues(project.id, [
            {"id": "i1", "identifier": "ENG-1", "title": "Original", "state": {"name": "Todo"}, "priority": 0, "url": ""},
        ])

        # Second poll — issue was updated
        linear_service.list_project_issues = AsyncMock(return_value=[
            {"id": "i1", "identifier": "ENG-1", "title": "Updated title", "state": {"name": "In Progress"}, "priority": 1, "url": ""},
        ])

        published: list = []
        original_publish = event_bus.publish

        def capture_publish(event):
            published.append(event)
            return original_publish(event)

        event_bus.publish = capture_publish

        poller = LinearPoller(settings, linear_service, store, event_bus)
        await poller._poll_all_projects()

        assert len(published) == 1
        assert published[0].event_type == EVENT_LINEAR_ISSUE_UPDATED

    @pytest.mark.asyncio
    async def test_publishes_deleted_events(
        self, settings, linear_service, store, event_bus,
    ) -> None:
        project = store.link_project(
            repo="my-repo",
            linear_project_id="proj-1",
            conversation_id=None,
            team_id="t1",
            project_data={"name": "P", "status": {"type": "started"}},
        )

        # First sync — creates issues
        store.sync_issues(project.id, [
            {"id": "i1", "identifier": "ENG-1", "title": "To delete", "state": {"name": "Todo"}, "priority": 0, "url": ""},
            {"id": "i2", "identifier": "ENG-2", "title": "Keep", "state": {"name": "Todo"}, "priority": 0, "url": ""},
        ])

        # Second poll — i1 is gone
        linear_service.list_project_issues = AsyncMock(return_value=[
            {"id": "i2", "identifier": "ENG-2", "title": "Keep", "state": {"name": "Todo"}, "priority": 0, "url": ""},
        ])

        published: list = []
        original_publish = event_bus.publish

        def capture_publish(event):
            published.append(event)
            return original_publish(event)

        event_bus.publish = capture_publish

        poller = LinearPoller(settings, linear_service, store, event_bus)
        await poller._poll_all_projects()

        # Should have at least a deleted event
        deleted_events = [e for e in published if e.event_type == EVENT_LINEAR_ISSUE_DELETED]
        assert len(deleted_events) == 1

    @pytest.mark.asyncio
    async def test_no_events_when_unchanged(
        self, settings, linear_service, store, event_bus,
    ) -> None:
        project = store.link_project(
            repo="my-repo",
            linear_project_id="proj-1",
            conversation_id=None,
            team_id="t1",
            project_data={"name": "P", "status": {"type": "started"}},
        )

        issues = [
            {"id": "i1", "identifier": "ENG-1", "title": "Same", "state": {"name": "Todo"}, "priority": 0, "url": ""},
        ]
        store.sync_issues(project.id, issues)

        linear_service.list_project_issues = AsyncMock(return_value=issues)

        published: list = []
        original_publish = event_bus.publish

        def capture_publish(event):
            published.append(event)
            return original_publish(event)

        event_bus.publish = capture_publish

        poller = LinearPoller(settings, linear_service, store, event_bus)
        await poller._poll_all_projects()

        assert len(published) == 0


class TestPollProjectErrorHandling:
    @pytest.mark.asyncio
    async def test_continues_on_project_error(
        self, settings, store, event_bus,
    ) -> None:
        """If one project fails, polling continues for others."""
        store.link_project(
            repo="repo-a",
            linear_project_id="proj-a",
            conversation_id=None,
            team_id="t1",
            project_data={"name": "A", "status": {"type": "started"}},
        )
        store.link_project(
            repo="repo-b",
            linear_project_id="proj-b",
            conversation_id=None,
            team_id="t1",
            project_data={"name": "B", "status": {"type": "started"}},
        )

        call_count = 0

        async def mock_list_issues(project_id, **kwargs):
            nonlocal call_count
            call_count += 1
            if project_id == "proj-a":
                raise RuntimeError("API error")
            return [
                {"id": "i1", "identifier": "ENG-1", "title": "Task", "state": {"name": "Todo"}, "priority": 0, "url": ""},
            ]

        mock_service = MagicMock(spec=LinearService)
        mock_service.list_project_issues = AsyncMock(side_effect=mock_list_issues)

        poller = LinearPoller(settings, mock_service, store, event_bus)
        await poller._poll_all_projects()

        # Both projects should have been attempted
        assert call_count == 2
        # Second project's issues should still sync
        issue = store.get_issue_by_linear_id("i1")
        assert issue is not None
