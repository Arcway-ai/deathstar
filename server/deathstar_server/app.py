from __future__ import annotations

import hmac
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from deathstar_server.app_state import settings
from deathstar_server.errors import AppError
from deathstar_server.routes import router
from deathstar_shared.models import ErrorCode

logger = logging.getLogger(__name__)

if not settings.api_token:
    logger.warning(
        "DEATHSTAR_API_TOKEN is not set — all API endpoints are unauthenticated. "
        "Set DEATHSTAR_API_TOKEN or store it in SSM to enable auth."
    )

app = FastAPI(title="DeathStar Control API", version="0.1.0")
app.include_router(router)

# Conditionally mount the web UI
if settings.enable_web_ui:
    from deathstar_server.web.routes import web_router

    app.include_router(web_router)

    # Prefer React build output (web/dist), fall back to legacy static dir
    _react_dist = Path(__file__).parent / "web" / "dist"
    _legacy_static = Path(__file__).parent / "web" / "static"
    _static_dir = _react_dist if _react_dist.is_dir() else _legacy_static
    if _static_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_static_dir / "assets") if (_static_dir / "assets").is_dir() else str(_static_dir)), name="web-static")

# Paths that skip bearer-token auth
_PUBLIC_PATHS = {"/v1/health", "/", "/index.html"}
_PUBLIC_PREFIXES = ("/static/", "/assets/")


@app.middleware("http")
async def authenticate_request(request: Request, call_next):
    if not settings.api_token:
        return await call_next(request)

    path = request.url.path
    if path in _PUBLIC_PATHS or any(path.startswith(p) for p in _PUBLIC_PREFIXES):
        return await call_next(request)

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
    if settings.enable_web_ui:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self'"
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


# Serve index.html at root when web UI is enabled (React SPA)
if settings.enable_web_ui:
    from fastapi.responses import FileResponse

    @app.get("/")
    def serve_index():
        _react_dist = Path(__file__).parent / "web" / "dist"
        if (_react_dist / "index.html").is_file():
            return FileResponse(str(_react_dist / "index.html"), media_type="text/html")
        # Fallback to legacy static
        index_path = Path(__file__).parent / "web" / "static" / "index.html"
        return FileResponse(str(index_path), media_type="text/html")
