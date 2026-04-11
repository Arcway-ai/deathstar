from __future__ import annotations

import asyncio
import logging

from deathstar_server.config import Settings
from deathstar_server.services.event_bus import (
    EVENT_LINEAR_ISSUE_CREATED,
    EVENT_LINEAR_ISSUE_DELETED,
    EVENT_LINEAR_ISSUE_UPDATED,
    EventBus,
    RepoEvent,
    SOURCE_LINEAR,
)
from deathstar_server.services.linear import LinearService
from deathstar_server.web.linear_store import LinearStore, SyncResult

logger = logging.getLogger(__name__)


class LinearPoller:
    """Polls Linear API for issue/project changes.

    Acts as a webhook fallback — iterates over all linked LinearProject
    rows, fetches their issues via LinearService, diffs against DB state
    via LinearStore.sync_issues(), and publishes RepoEvents for any
    changes detected.

    Follows the GitHubPoller pattern: asyncio background task with
    start()/stop() lifecycle management.
    """

    def __init__(
        self,
        settings: Settings,
        linear_service: LinearService,
        linear_store: LinearStore,
        event_bus: EventBus,
    ) -> None:
        self._settings = settings
        self._linear_service = linear_service
        self._linear_store = linear_store
        self._event_bus = event_bus
        self._interval = settings.linear_poll_interval_seconds
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """Start the polling background task."""
        if not self._settings.linear_api_key:
            logger.info("Linear poller disabled — no LINEAR_API_KEY configured")
            return
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop(), name="linear-poller")
        logger.info("Linear poller started (interval=%ds)", self._interval)

    async def stop(self) -> None:
        """Stop the polling background task."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Linear poller stopped")

    async def _poll_loop(self) -> None:
        """Main polling loop — runs until stopped."""
        while self._running:
            try:
                projects = self._linear_store.list_all_projects()
                for project in projects:
                    if not self._running:
                        break
                    await self._poll_project(project)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Linear poller error")

            # Sleep in 1-second increments for responsive shutdown
            for _ in range(self._interval):
                if not self._running:
                    break
                await asyncio.sleep(1)

    async def _poll_all_projects(self) -> None:
        """Poll all linked Linear projects for issue changes.

        Public entry point — can be called directly (e.g. in tests)
        without the poller being started.
        """
        projects = self._linear_store.list_all_projects()

        if not projects:
            logger.debug("Linear poller: no linked projects to poll")
            return

        for project in projects:
            try:
                await self._poll_project(project)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "Linear poller: error polling project %s (%s)",
                    project.name,
                    project.linear_project_id,
                    exc_info=True,
                )

    async def _poll_project(self, project: object) -> None:
        """Poll a single project and sync its issues."""
        linear_project_id = project.linear_project_id  # type: ignore[attr-defined]
        project_name = project.name  # type: ignore[attr-defined]
        repo = project.repo  # type: ignore[attr-defined]
        internal_id = project.id  # type: ignore[attr-defined]

        logger.debug(
            "Linear poller: polling project %s (%s) for repo %s",
            project_name, linear_project_id, repo,
        )

        # Fetch current issues from Linear API
        remote_issues = await self._linear_service.list_project_issues(
            linear_project_id,
        )

        # Sync against local DB state
        result = self._linear_store.sync_issues(internal_id, remote_issues)

        if result.created or result.updated or result.deleted_ids:
            logger.info(
                "Linear poller: project %s (%s) — created=%d updated=%d deleted=%d",
                project_name,
                linear_project_id,
                result.created,
                result.updated,
                len(result.deleted_ids),
            )
            self._publish_sync_events(repo, result, remote_issues)
        else:
            logger.debug(
                "Linear poller: project %s — no changes",
                project_name,
            )

    def _publish_sync_events(
        self,
        repo: str,
        result: SyncResult,
        remote_issues: list[dict],
    ) -> None:
        """Publish RepoEvents for changes detected during a sync."""
        # For created issues, publish a summary event
        if result.created:
            self._event_bus.publish(RepoEvent(
                event_type=EVENT_LINEAR_ISSUE_CREATED,
                repo=repo,
                source=SOURCE_LINEAR,
                data={
                    "count": result.created,
                    "source": "poller",
                },
            ))

        # For updated issues, publish a summary event
        if result.updated:
            self._event_bus.publish(RepoEvent(
                event_type=EVENT_LINEAR_ISSUE_UPDATED,
                repo=repo,
                source=SOURCE_LINEAR,
                data={
                    "count": result.updated,
                    "source": "poller",
                },
            ))

        # For deleted issues, publish individual events
        for deleted_id in result.deleted_ids:
            self._event_bus.publish(RepoEvent(
                event_type=EVENT_LINEAR_ISSUE_DELETED,
                repo=repo,
                source=SOURCE_LINEAR,
                data={
                    "linear_issue_id": deleted_id,
                    "source": "poller",
                },
            ))
