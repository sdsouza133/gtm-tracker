"""The app: the JSON API under /api, and the built front end for every other path."""

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api import auth_routes
from app.config import get_settings
from app.db import get_engine

log = logging.getLogger("gtm_tracker")

CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; font-src 'self'; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)
HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


def create_app() -> FastAPI:
    settings = get_settings()
    # No public docs or schema: the schema is written to openapi.json by `python -m app.cli openapi` instead.
    app = FastAPI(title="GTM Tracker", docs_url=None, openapi_url=None, redoc_url=None)
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    @app.middleware("http")
    async def headers_and_log(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        started = time.perf_counter()
        response = await call_next(request)
        for name, value in HEADERS.items():
            response.headers.setdefault(name, value)
        if settings.secure_cookies:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        response.headers["X-Request-Id"] = request_id
        log.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,  # never the query string: it can carry tokens
                "status": response.status_code,
                "ms": round((time.perf_counter() - started) * 1000),
                "request_id": request_id,
            },
        )
        return response

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    def readyz() -> JSONResponse:
        try:
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:  # the database is down or unreachable
            log.exception("readiness check failed")
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return JSONResponse({"status": "ok"})

    app.include_router(auth_routes.router)

    static = Path(settings.static_dir)
    if (static / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> Response:
            if path.startswith("api/"):
                return JSONResponse({"detail": "Not found"}, status_code=404)
            file = (static / path).resolve()
            if path and file.is_file() and file.is_relative_to(static.resolve()):
                return FileResponse(file)
            return FileResponse(static / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
