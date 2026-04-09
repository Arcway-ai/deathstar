from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import AsyncIterator

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

logger = logging.getLogger(__name__)

# Event types — local
EVENT_LOCAL_COMMIT = "local_commit"
EVENT_LOCAL_CHECKOUT = "local_checkout"
EVENT_REPO_DIRTY = "repo_dirty"
EVENT_BRANCH_UPDATE = "branch_update"

# Event types — queue
EVENT_QUEUE_PROCESSING = "queue_processing"
EVENT_QUEUE_COMPLETED = "queue_completed"
EVENT_QUEUE_FAILED = "queue_failed"

# Event types — GitHub
EVENT_PUSH = "push"
EVENT_PR_UPDATE = "pr_update"
EVENT_CI_STATUS = "ci_status"

# Sources
SOURCE_LOCAL = "local"
SOURCE_GITHUB = "github"
SOURCE_AGENT = "agent"

# Dedup TTL
_DEDUP_TTL_SECONDS = 120


@dataclass(frozen=True)
class RepoEvent:
    """A single event related to a repository."""

    event_type: str
    repo: str
    source: str
    data: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def dedup_key(self) -> str:
        """Stable key for deduplication (type + repo + data hash)."""
        raw = f"{self.event_type}:{self.repo}:{self.source}"
        # Include all data fields for uniqueness (json.dumps for complex types)
        for key in sorted(self.data.keys()):
            val = self.data[key]
            if isinstance(val, (str, int, float, bool)):
                raw += f":{key}={val}"
            elif isinstance(val, (list, dict)):
                raw += f":{key}={json.dumps(val, sort_keys=True, default=str)}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class _Subscriber:
    """Internal subscriber state using anyio memory object streams."""

    id: str
    repo: str | None  # None = all repos
    send: MemoryObjectSendStream[RepoEvent]
    recv: MemoryObjectReceiveStream[RepoEvent]


class EventBus:
    """In-process asyncio pub/sub for repo events.

    Supports repo-filtered subscriptions and deduplication.
    Designed for single-instance architecture (no Redis needed).
    """

    def __init__(self, dedup_ttl: float = _DEDUP_TTL_SECONDS) -> None:
        self._subscribers: dict[str, _Subscriber] = {}
        self._dedup_cache: dict[str, float] = {}
        self._dedup_ttl = dedup_ttl

    def publish(self, event: RepoEvent) -> int:
        """Publish an event to all matching subscribers.

        Returns the number of subscribers that received the event.
        """
        # Dedup check
        key = event.dedup_key()
        now = time.time()
        self._evict_stale_dedup(now)

        if key in self._dedup_cache:
            logger.debug("dedup: dropping duplicate event %s for %s", event.event_type, event.repo)
            return 0
        self._dedup_cache[key] = now

        delivered = 0
        for sub in list(self._subscribers.values()):
            if sub.repo is not None and sub.repo != event.repo:
                continue
            try:
                sub.send.send_nowait(event)
                delivered += 1
            except (anyio.WouldBlock, anyio.ClosedResourceError):
                logger.warning(
                    "subscriber %s buffer full or closed, dropping event %s",
                    sub.id,
                    event.event_type,
                )
        return delivered

    def subscribe(self, repo: str | None = None) -> _SubscriptionContext:
        """Subscribe to events, optionally filtered by repo.

        Usage::

            async with event_bus.subscribe("my-repo") as events:
                async for event in events:
                    ...
        """
        return _SubscriptionContext(self, repo)

    def _add_subscriber(self, repo: str | None) -> _Subscriber:
        send, recv = anyio.create_memory_object_stream[RepoEvent](max_buffer_size=256)
        sub = _Subscriber(
            id=uuid.uuid4().hex[:12],
            repo=repo,
            send=send,
            recv=recv,
        )
        self._subscribers[sub.id] = sub
        logger.debug("subscriber %s added (repo=%s)", sub.id, repo)
        return sub

    def _remove_subscriber(self, sub_id: str) -> None:
        sub = self._subscribers.pop(sub_id, None)
        if sub:
            sub.send.close()
        logger.debug("subscriber %s removed", sub_id)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def _evict_stale_dedup(self, now: float) -> None:
        cutoff = now - self._dedup_ttl
        stale = [k for k, ts in self._dedup_cache.items() if ts < cutoff]
        for k in stale:
            del self._dedup_cache[k]


class _SubscriptionContext:
    """Async context manager for event subscriptions."""

    def __init__(self, bus: EventBus, repo: str | None) -> None:
        self._bus = bus
        self._repo = repo
        self._sub: _Subscriber | None = None

    async def __aenter__(self) -> AsyncIterator[RepoEvent]:
        self._sub = self._bus._add_subscriber(self._repo)
        return self._iter()

    async def __aexit__(self, *exc) -> None:
        if self._sub:
            self._bus._remove_subscriber(self._sub.id)
            self._sub = None

    async def _iter(self) -> AsyncIterator[RepoEvent]:
        assert self._sub is not None
        async for event in self._sub.recv:
            yield event
