from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
from pathlib import Path

import httpx

from deathstar_server.config import Settings
from deathstar_server.services.event_bus import (
    EVENT_CI_STATUS,
    EVENT_PR_UPDATE,
    EVENT_PUSH,
    EventBus,
    RepoEvent,
    SOURCE_GITHUB,
)

logger = logging.getLogger(__name__)

# Back off when rate limit is getting low
_RATE_LIMIT_FLOOR = 500


class GitHubPoller:
    """Polls GitHub Events API for changes to cloned repos.

    Uses ETag caching so 304 responses don't count against the rate limit.
    Translates PushEvent, PullRequestEvent, and StatusEvent into RepoEvents.
    """

    def __init__(
        self,
        settings: Settings,
        event_bus: EventBus,
    ) -> None:
        self._settings = settings
        self._event_bus = event_bus
        self._interval = settings.github_poll_interval_seconds
        self._task: asyncio.Task | None = None
        # repo_name -> ETag header for conditional requests
        self._etags: dict[str, str] = {}
        # repo_name -> last seen event ID to avoid reprocessing
        self._last_event_ids: dict[str, set[str]] = {}
        self._running = False

    async def start(self) -> None:
        """Start the background polling loop."""
        if not self._settings.github_token:
            logger.info("GitHub poller disabled — no GITHUB_TOKEN configured")
            return
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop(), name="github-poller")
        logger.info("GitHub poller started (interval=%ds)", self._interval)

    async def stop(self) -> None:
        """Stop the polling loop gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("GitHub poller stopped")

    def _discover_repos(self) -> list[tuple[str, str, str]]:
        """Discover cloned repos and their GitHub owner/repo.

        Returns list of (repo_name, owner, repo) tuples.
        """
        projects_root = self._settings.projects_root
        if not projects_root.is_dir():
            return []

        results = []
        for repo_dir in projects_root.iterdir():
            if not repo_dir.is_dir() or not (repo_dir / ".git").exists():
                continue
            parsed = self._parse_origin(repo_dir)
            if parsed:
                owner, repo = parsed
                results.append((repo_dir.name, owner, repo))
        return results

    @staticmethod
    def _parse_origin(repo_dir: Path) -> tuple[str, str] | None:
        """Extract GitHub owner/repo from a local repo's origin remote."""
        try:
            result = subprocess.run(
                ["git", "-C", str(repo_dir), "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None

        url = result.stdout.strip()
        # SSH: git@github.com:owner/repo.git
        # HTTPS: https://github.com/owner/repo.git
        for pattern in (
            r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^.]+?)(?:\.git)?$",
            r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^.]+?)(?:\.git)?$",
        ):
            m = re.match(pattern, url)
            if m:
                return m.group("owner"), m.group("repo")
        return None

    async def _poll_loop(self) -> None:
        """Main polling loop — runs until stopped."""
        while self._running:
            try:
                repos = self._discover_repos()
                if repos:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        for repo_name, owner, repo in repos:
                            if not self._running:
                                break
                            await self._poll_repo(client, repo_name, owner, repo)
            except asyncio.CancelledError:
                raise
            except (httpx.HTTPError, OSError, KeyError, ValueError, json.JSONDecodeError):
                logger.exception("GitHub poller error")

            # Sleep in small increments so we can stop quickly
            for _ in range(self._interval):
                if not self._running:
                    break
                await asyncio.sleep(1)

    async def _poll_repo(
        self,
        client: httpx.AsyncClient,
        repo_name: str,
        owner: str,
        repo: str,
    ) -> None:
        """Poll a single repo's events endpoint."""
        headers = {
            "Authorization": f"Bearer {self._settings.github_token}",
            "Accept": "application/vnd.github+json",
        }

        # Conditional request with ETag
        cache_key = f"{owner}/{repo}"
        etag = self._etags.get(cache_key)
        if etag:
            headers["If-None-Match"] = etag

        try:
            response = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/events",
                params={"per_page": 30},
                headers=headers,
            )
        except httpx.HTTPError as exc:
            logger.warning("GitHub API error for %s/%s: %s", owner, repo, exc)
            return

        # 304 Not Modified — no new events, and it's free
        if response.status_code == 304:
            return

        if response.status_code != 200:
            logger.warning(
                "GitHub events API returned %d for %s/%s",
                response.status_code,
                owner,
                repo,
            )
            return

        # Store new ETag
        new_etag = response.headers.get("ETag")
        if new_etag:
            self._etags[cache_key] = new_etag

        # Check rate limit
        remaining = response.headers.get("X-RateLimit-Remaining")
        if remaining:
            try:
                if int(remaining) < _RATE_LIMIT_FLOOR:
                    logger.warning(
                        "GitHub rate limit low (%s remaining) — consider increasing poll interval",
                        remaining,
                    )
            except ValueError:
                pass

        try:
            events = response.json()
        except (json.JSONDecodeError, ValueError):
            logger.warning("GitHub events API returned non-JSON for %s/%s", owner, repo)
            return
        if not isinstance(events, list):
            return

        seen = self._last_event_ids.setdefault(cache_key, set())

        for gh_event in events:
            event_id = str(gh_event.get("id", ""))
            if not event_id or event_id in seen:
                continue
            seen.add(event_id)

            repo_event = self._translate_event(repo_name, gh_event)
            if repo_event:
                self._event_bus.publish(repo_event)

        # Cap the seen set to prevent unbounded growth
        if len(seen) > 500:
            # Keep only the 200 most recent (events are ordered newest-first)
            recent_ids = {str(e.get("id", "")) for e in events[:200]}
            seen.clear()
            seen.update(recent_ids)

    @staticmethod
    def _translate_event(repo_name: str, gh_event: dict) -> RepoEvent | None:
        """Translate a GitHub API event into a RepoEvent."""
        event_type = gh_event.get("type")
        payload = gh_event.get("payload", {})
        actor = gh_event.get("actor", {}).get("login", "unknown")

        if event_type == "PushEvent":
            commits = []
            for c in payload.get("commits", [])[:10]:
                commits.append({
                    "sha": c.get("sha", "")[:7],
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
                    "sender": actor,
                    "size": payload.get("size", 0),
                },
            )

        if event_type == "PullRequestEvent":
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
                    "sender": actor,
                },
            )

        if event_type == "StatusEvent":
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
