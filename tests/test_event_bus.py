from __future__ import annotations

import asyncio

import pytest

from deathstar_server.services.event_bus import (
    EVENT_LOCAL_COMMIT,
    EVENT_PUSH,
    EventBus,
    RepoEvent,
    SOURCE_GITHUB,
    SOURCE_LOCAL,
)


@pytest.fixture
def bus() -> EventBus:
    return EventBus(dedup_ttl=2.0)


def _event(event_type: str = EVENT_PUSH, repo: str = "my-repo", **data) -> RepoEvent:
    return RepoEvent(event_type=event_type, repo=repo, source=SOURCE_GITHUB, data=data)


# ---------------------------------------------------------------------------
# Basic pub/sub
# ---------------------------------------------------------------------------


async def test_publish_no_subscribers(bus: EventBus):
    """Publishing with no subscribers returns 0."""
    count = bus.publish(_event())
    assert count == 0


async def test_subscribe_receives_events(bus: EventBus):
    """A subscriber receives published events."""
    received: list[RepoEvent] = []

    async with bus.subscribe("my-repo") as events:
        bus.publish(_event(repo="my-repo", sha="abc"))

        # Drain one event
        event = await asyncio.wait_for(events.__anext__(), timeout=1.0)
        received.append(event)

    assert len(received) == 1
    assert received[0].event_type == EVENT_PUSH
    assert received[0].data["sha"] == "abc"


async def test_repo_filtering(bus: EventBus):
    """Subscribers only get events for their subscribed repo."""
    received: list[RepoEvent] = []

    async with bus.subscribe("repo-a") as events:
        bus.publish(_event(repo="repo-b", sha="skip"))
        bus.publish(_event(repo="repo-a", sha="match"))

        event = await asyncio.wait_for(events.__anext__(), timeout=1.0)
        received.append(event)

    assert len(received) == 1
    assert received[0].data["sha"] == "match"


async def test_wildcard_subscribe(bus: EventBus):
    """Subscribing with repo=None gets all events."""
    received: list[RepoEvent] = []

    async with bus.subscribe(None) as events:
        bus.publish(_event(repo="repo-a"))
        bus.publish(_event(repo="repo-b"))

        for _ in range(2):
            event = await asyncio.wait_for(events.__anext__(), timeout=1.0)
            received.append(event)

    assert len(received) == 2


async def test_fan_out(bus: EventBus):
    """Multiple subscribers to the same repo all receive the event."""
    received_a: list[RepoEvent] = []
    received_b: list[RepoEvent] = []

    async with bus.subscribe("my-repo") as events_a, bus.subscribe("my-repo") as events_b:
        count = bus.publish(_event(repo="my-repo"))
        assert count == 2

        event_a = await asyncio.wait_for(events_a.__anext__(), timeout=1.0)
        event_b = await asyncio.wait_for(events_b.__anext__(), timeout=1.0)
        received_a.append(event_a)
        received_b.append(event_b)

    assert len(received_a) == 1
    assert len(received_b) == 1


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


async def test_dedup_identical_events(bus: EventBus):
    """Identical events within TTL are deduplicated."""
    event = _event(repo="my-repo", sha="abc123")

    async with bus.subscribe("my-repo"):
        count1 = bus.publish(event)
        count2 = bus.publish(event)

        assert count1 == 1
        assert count2 == 0  # Deduped


async def test_different_events_not_deduped(bus: EventBus):
    """Events with different data are NOT deduplicated."""
    async with bus.subscribe("my-repo"):
        count1 = bus.publish(_event(repo="my-repo", sha="aaa"))
        count2 = bus.publish(_event(repo="my-repo", sha="bbb"))

        assert count1 == 1
        assert count2 == 1


# ---------------------------------------------------------------------------
# Subscriber lifecycle
# ---------------------------------------------------------------------------


async def test_subscriber_cleanup(bus: EventBus):
    """Exiting the context manager removes the subscriber."""
    assert bus.subscriber_count == 0

    async with bus.subscribe("my-repo"):
        assert bus.subscriber_count == 1

    assert bus.subscriber_count == 0


# ---------------------------------------------------------------------------
# Event model
# ---------------------------------------------------------------------------


def test_repo_event_dedup_key():
    """dedup_key produces stable, distinct keys."""
    e1 = RepoEvent(event_type=EVENT_PUSH, repo="r", source=SOURCE_GITHUB, data={"sha": "a"})
    e2 = RepoEvent(event_type=EVENT_PUSH, repo="r", source=SOURCE_GITHUB, data={"sha": "b"})
    e3 = RepoEvent(event_type=EVENT_LOCAL_COMMIT, repo="r", source=SOURCE_LOCAL, data={"sha": "a"})

    assert e1.dedup_key() == e1.dedup_key()  # Stable
    assert e1.dedup_key() != e2.dedup_key()  # Different data
    assert e1.dedup_key() != e3.dedup_key()  # Different type + source
