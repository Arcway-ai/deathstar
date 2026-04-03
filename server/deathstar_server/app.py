from __future__ import annotations

import asyncio
import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from deathstar_server.app_state import event_bus, settings, worktree_manager
from deathstar_server.errors import AppError
from deathstar_server.routes import router
from deathstar_server.services.github_poller import GitHubPoller
from deathstar_server.session import (
    SESSION_COOKIE_NAME,
    cookie_params,
    generate_session_token,
    validate_session_token,
)
from deathstar_server.web.agent_ws import agent_ws_router
from deathstar_server.web.routes import web_router
from deathstar_server.web.terminal import terminal_router
from deathstar_server.web.webhooks import webhook_router
from deathstar_shared.models import ErrorCode

logger = logging.getLogger(__name__)

if not settings.api_token:
    logger.warning(
        "DEATHSTAR_API_TOKEN is not set — all API endpoints are unauthenticated. "
        "Set DEATHSTAR_API_TOKEN or store it in SSM to enable auth."
    )

_github_poller = GitHubPoller(settings, event_bus)


async def _worktree_reaper() -> None:
    """Periodically clean up stale worktrees not tied to active sessions."""
    from deathstar_server.app_state import agent_runner

    while True:
        await asyncio.sleep(300)  # Every 5 minutes
        try:
            # Take a snapshot to avoid iteration over a mutating dict
            locks_snapshot = agent_runner.get_active_branches()
            projects = settings.projects_root
            if not projects.is_dir():
                continue
            for entry in projects.iterdir():
                if not entry.is_dir() or entry.name.startswith("."):
                    continue
                git_dir = entry / ".git"
                if not git_dir.exists():
                    continue
                # Collect active branches for this repo from snapshot
                active = {
                    branch for (repo, branch), _ in locks_snapshot.items()
                    if repo == entry.name
                }
                removed = worktree_manager.cleanup_stale(entry, active)
                if removed:
                    logger.info("worktree reaper: cleaned %d stale worktrees for %s", removed, entry.name)
        except Exception:
            logger.warning("worktree reaper error", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start/stop background services."""
    from deathstar_server.app_state import agent_runner, queue_worker

    await _github_poller.start()
    await agent_runner.start()
    await queue_worker.start()
    reaper_task = asyncio.create_task(_worktree_reaper(), name="worktree-reaper")
    yield
    reaper_task.cancel()
    await queue_worker.stop()
    await agent_runner.stop()
    await _github_poller.stop()


app = FastAPI(title="DeathStar Control API", version="0.1.0", lifespan=lifespan)
app.include_router(router)
app.include_router(web_router)
app.include_router(agent_ws_router)
app.include_router(terminal_router)
app.include_router(webhook_router)

# Mount React build output (web/dist/assets)
_react_dist = Path(__file__).parent / "web" / "dist"
_assets_dir = _react_dist / "assets"
if _assets_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="web-static")

# Paths that skip bearer-token auth
_PUBLIC_PATHS = {
    "/v1/health", "/", "/index.html", "/favicon.svg",
    "/web/api/auth/session", "/web/api/webhooks/github",
}
_PUBLIC_PREFIXES = ("/assets/",)

# API path prefixes that require auth — everything else is an SPA route
_API_PREFIXES = ("/v1/", "/web/api/")


def _is_api_path(path: str) -> bool:
    """True if this path is an API endpoint (not an SPA route)."""
    return any(path.startswith(p) for p in _API_PREFIXES)


def _is_spa_route(path: str) -> bool:
    """True if this path should be served by index.html (SPA catch-all)."""
    if path in _PUBLIC_PATHS:
        return False
    if any(path.startswith(p) for p in _PUBLIC_PREFIXES):
        return False
    if _is_api_path(path):
        return False
    # Has a file extension → probably a static asset
    if "." in path.rsplit("/", 1)[-1]:
        return False
    return True


@app.middleware("http")
async def authenticate_request(request: Request, call_next):
    if not settings.api_token:
        return await call_next(request)

    path = request.url.path
    if path in _PUBLIC_PATHS or any(path.startswith(p) for p in _PUBLIC_PREFIXES) or _is_spa_route(path):
        return await call_next(request)

    # Web API paths: accept session cookie OR bearer token
    if path.startswith("/web/api/"):
        session_cookie = request.cookies.get(SESSION_COOKIE_NAME)
        if session_cookie and validate_session_token(session_cookie, settings.api_token):
            return await call_next(request)

    # Bearer token auth (CLI /v1/ paths, and fallback for /web/api/)
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    else:
        token = ""

    if not hmac.compare_digest(token, settings.api_token):
        return JSONResponse(
            status_code=401,
            content={"code": ErrorCode.AUTH_ERROR.value, "message": "invalid or missing API token"},
        )

    return await call_next(request)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    # Restrict connect-src to same-origin WebSockets only (wss: for TLS, ws: for local dev)
    host = request.headers.get("host", "")
    ws_origin = f"wss://{host} ws://{host}" if host else "wss: ws:"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        f"connect-src 'self' {ws_origin}"
    )
    return response


@app.exception_handler(AppError)
async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_envelope().model_dump(mode="json"),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={
            "code": ErrorCode.INTERNAL_ERROR.value,
            "message": "an unexpected error occurred",
            "retryable": False,
        },
    )


def _serve_index_html(request: Request):
    """Serve index.html and set a session cookie for web UI auth."""
    index_path = Path(__file__).parent / "web" / "dist" / "index.html"
    if not index_path.is_file():
        return JSONResponse(status_code=404, content={"detail": "index.html not found — run 'cd web && npm run build'"})

    html = index_path.read_text()
    response = HTMLResponse(html)

    # Set session cookie so the frontend can authenticate API/WebSocket requests
    if settings.api_token:
        token = generate_session_token(settings.api_token)
        params = cookie_params(is_https=request.url.scheme == "https")
        response.set_cookie(value=token, **params)

    return response


@app.get("/")
def serve_index(request: Request):
    return _serve_index_html(request)


@app.get("/favicon.svg")
def serve_favicon():
    candidates = [
        Path(__file__).parent / "web" / "dist" / "favicon.svg",
        Path("/app/web/dist/favicon.svg"),
        Path("/app/web/public/favicon.svg"),
    ]
    for path in candidates:
        if path.is_file():
            return FileResponse(str(path), media_type="image/svg+xml")
    return JSONResponse(status_code=404, content={"detail": "favicon not found"})


# SPA catch-all — must be LAST so it doesn't shadow specific routes
@app.get("/{full_path:path}")
def serve_spa(request: Request, full_path: str):
    """Serve index.html for client-side routes (e.g. /:repo, /:repo/c/:id)."""
    path = f"/{full_path}"
    if not _is_spa_route(path):
        return JSONResponse(status_code=404, content={"detail": "not found"})
    return _serve_index_html(request)
