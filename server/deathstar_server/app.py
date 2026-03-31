from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from deathstar_server.app_state import event_bus, settings
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start/stop background services."""
    await _github_poller.start()
    yield
    await _github_poller.stop()


app = FastAPI(title="DeathStar Control API", version="0.1.0", lifespan=lifespan)
app.include_router(router)
app.include_router(web_router)
app.include_router(agent_ws_router)
app.include_router(terminal_router)
app.include_router(webhook_router)

# Prefer React build output (web/dist), fall back to vanilla static dir
_react_dist = Path(__file__).parent / "web" / "dist"
_legacy_static = Path(__file__).parent / "web" / "static"
_static_dir = _react_dist if _react_dist.is_dir() else _legacy_static
if _static_dir.is_dir():
    _mount_path = "/assets" if _static_dir == _react_dist and (_static_dir / "assets").is_dir() else "/static"
    _mount_dir = str(_static_dir / "assets") if _mount_path == "/assets" else str(_static_dir)
    app.mount(_mount_path, StaticFiles(directory=_mount_dir), name="web-static")

# Paths that skip bearer-token auth
_PUBLIC_PATHS = {
    "/v1/health", "/", "/index.html", "/favicon.svg",
    "/web/api/auth/session", "/web/api/webhooks/github",
}
_PUBLIC_PREFIXES = ("/static/", "/assets/")

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
    _react_dist = Path(__file__).parent / "web" / "dist"
    if (_react_dist / "index.html").is_file():
        index_path = _react_dist / "index.html"
    else:
        index_path = Path(__file__).parent / "web" / "static" / "index.html"

    if not index_path.is_file():
        return JSONResponse(status_code=404, content={"detail": "index.html not found"})

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
    _project_root = Path(__file__).parent.parent.parent
    candidates = [
        Path(__file__).parent / "web" / "dist" / "favicon.svg",
        Path(__file__).parent / "web" / "static" / "favicon.svg",
        _project_root / "web" / "dist" / "favicon.svg",
        _project_root / "web" / "public" / "favicon.svg",
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
