# Real-Time Event System: GitHub Webhooks + Event Broadcasting

## Context

DeathStar is being productionized for team use. Multiple users will make concurrent changes to repos. The current UI only refreshes state after local actions (save, agent done, branch switch). External changes (pushes from teammates, CI, GitHub) are invisible until manual refresh. We need real-time sync so every connected client sees changes as they happen.

**Network constraint:** The instance is behind Tailscale by default — GitHub can't reach it for webhooks. The design uses **GitHub API polling as primary** (works everywhere) with an **optional webhook receiver** for setups that expose a public URL.

## Architecture

```
GitHub ─── (webhook or polling) ──→ Webhook Handler / Poller
                                           │
                                           ▼
Local events (save, agent, checkout) ──→ EventBus (asyncio pub/sub)
                                           │
                                           ▼
                                     All connected clients
                                     (via agent WebSocket
                                      "repo_event" messages)
```

- **EventBus**: In-process asyncio pub/sub (no Redis — single-instance architecture). Subscribers get `asyncio.Queue`s filtered by repo.
- **GitHub Poller**: Background task polls `/repos/{owner}/{repo}/events` every 30s with `ETag`/`If-None-Match` (304s don't count against rate limit).
- **Webhook Receiver**: Optional `POST /web/api/webhooks/github` with HMAC-SHA256 verification. For public setups or smee.io dev proxy.
- **Delivery**: Extends existing agent WebSocket with `repo_event` message type. No second WebSocket connection needed.
- **Dedup**: SHA+event_type cache (120s TTL) prevents duplicates when both polling and webhooks are active.

## Event Types

| Event | Source | Data |
|-------|--------|------|
| `push` | github | `ref`, `commits [{sha, message, author}]`, `sender` |
| `pr_update` | github | `action`, `number`, `title`, `state`, `head_branch`, `sender` |
| `ci_status` | github | `sha`, `state`, `context`, `target_url` |
| `local_commit` | local | `sha`, `message`, `branch` |
| `local_checkout` | local | `from_branch`, `to_branch` |
| `repo_dirty` | local | `dirty`, `branch` |
| `branch_update` | local/github | `branches`, `current` |

All wrapped in: `{"type": "repo_event", "event_type": "...", "repo": "...", "source": "...", "data": {...}}`

## Files to Create

### `server/deathstar_server/services/event_bus.py`
- `RepoEvent` dataclass (event_type, repo, timestamp, source, data)
- `EventBus` class: `publish(event)`, `subscribe(repo) -> AsyncIterator[RepoEvent]`
- Dict of subscriber queues keyed by ID, filtered by repo
- Dedup cache: `dict[str, float]` with 120s TTL

### `server/deathstar_server/services/github_poller.py`
- `GitHubPoller` class with `start()` / `stop()` lifecycle
- Polls `/repos/{owner}/{repo}/events` per cloned repo every 30s
- ETag caching for conditional requests (304 = free)
- Rate limit awareness: back off when `X-RateLimit-Remaining` < 500
- Translates `PushEvent`, `PullRequestEvent`, `StatusEvent` → `RepoEvent`

### `server/deathstar_server/web/webhooks.py`
- `webhook_router = APIRouter()`
- `POST /web/api/webhooks/github` — HMAC-SHA256 verification, event translation, publish to bus
- Only active when `GITHUB_WEBHOOK_SECRET` is set

## Files to Modify

### `server/deathstar_server/config.py`
- Add `github_webhook_secret: str | None` (from `GITHUB_WEBHOOK_SECRET`)
- Add `github_poll_interval_seconds: int` (from `GITHUB_POLL_INTERVAL`, default 30)

### `server/deathstar_server/app_state.py`
- Add `event_bus = EventBus()` singleton
- Add `github_poller = GitHubPoller(...)` singleton

### `server/deathstar_server/app.py`
- Add `lifespan` context manager to start/stop the poller
- Register `webhook_router`
- Add `/web/api/webhooks/github` to `_PUBLIC_PATHS` (HMAC self-authenticates)

### `server/deathstar_server/web/agent_ws.py`
- Handle `subscribe_events` message type from client
- Start `_forward_events()` background task per connection that subscribes to event bus and sends `repo_event` messages
- Publish `local_commit` / `repo_dirty` events after agent writes

### `server/deathstar_server/web/routes.py`
- Publish `local_commit` after `quick_save`
- Publish `local_checkout` after `checkout_branch`
- Publish `branch_update` after `create_branch` / `delete_branch`

### `web/src/agentSocket.ts`
- Add `onRepoEvent` callback
- Add `subscribeEvents(repo)` method
- Handle `repo_event` message type

### `web/src/store.ts`
- Wire `onRepoEvent` callback — auto-refresh commits/context/repos/PRs based on event type
- Send `subscribe_events` on connect and repo change

### `.env.example`
- Add `GITHUB_WEBHOOK_SECRET` and `GITHUB_POLL_INTERVAL`

## Implementation Order

| Phase | What | Scope |
|-------|------|-------|
| 1 | **Event Bus** — create `event_bus.py`, add singleton, write tests | Backend only |
| 2 | **Local Event Publishing** — publish from routes + agent_ws after save/checkout/writes | Backend only |
| 3 | **WebSocket Event Delivery** — `subscribe_events` handling, forwarding task, frontend wiring | Full stack |
| 4 | **GitHub Poller** — background polling, ETag caching, rate limiting, lifespan | Backend only |
| 5 | **Webhook Receiver** — HMAC verification, event translation (optional for public setups) | Backend only |

## Design Decisions

### Why extend the agent WebSocket instead of adding a new one?
The agent WebSocket is already established per session. Adding a second connection doubles connection management and auth handling. The agent WS already has `_send()` that silently handles disconnects. Idle clients (no agent running) simply receive `repo_event` messages on the same socket.

### Why polling over webhooks as primary?
The Tailscale-first network model means GitHub cannot reach the instance by default. Polling works universally. The 30-second delay is acceptable for team awareness. The webhook path exists for operators who want real-time delivery and can expose a URL.

### Why in-process asyncio bus instead of Redis/NATS?
The architecture is explicitly single-instance. An in-process bus has zero operational overhead, zero additional failure modes, and zero additional dependencies. If DeathStar ever goes multi-instance, the bus interface (`publish`/`subscribe`) is trivially swappable to Redis pub/sub.

### Why dedup cache?
When both polling and webhooks are active, the same push event arrives twice. The dedup cache (keyed on delivery ID or commit SHA + event type, 120s TTL) prevents duplicate UI refreshes.

## Verification

1. `uv run pytest tests/ -v` — no regressions
2. Unit tests: EventBus pub/sub fan-out, repo filtering, dedup
3. Unit tests: Webhook HMAC verification (valid/invalid signatures)
4. Unit tests: Poller ETag handling, event translation, rate limit backoff
5. Integration: FastAPI TestClient → save → event bus subscriber receives `local_commit`
6. Integration: WebSocket client → `subscribe_events` → HTTP save → receives `repo_event`
7. Manual: Two browser tabs, agent writes in tab A → tab B sees commit list update
8. Manual: Push from another machine → poller picks up within 30s → both tabs refresh
