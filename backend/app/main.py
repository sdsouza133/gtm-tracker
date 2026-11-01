"""The app: the JSON API under /api, and the built front end for every other path."""

import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api import auth_routes, backup, companies, enrich, fractional, magnets, moves, people, radar, today
from app.config import get_settings
from app.db import get_engine, session_factory
from app.radar import run as radar_run
from app.services.outreach import NotFoundError, RuleError

log = logging.getLogger("gtm_tracker")

# Google's sign-in button is the one thing loaded from elsewhere: its script, its iframe, and its stylesheet, each
# limited to the paths Google documents for it.
GSI = "https://accounts.google.com/gsi"
CSP = (
    f"default-src 'self'; img-src 'self' data:; style-src 'self' {GSI}/style; script-src 'self' {GSI}/client; "
    f"font-src 'self'; connect-src 'self' {GSI}/; frame-src {GSI}/; frame-ancestors 'none'; base-uri 'none'; "
    "form-action 'self'"
)
REPORT_LINK = re.compile(r"^(/(?:api/public/magnets|m)/[^/]+/)[^/]+")


def log_path(path: str) -> str:
    """The path as logged: a lead magnet report's token is the only thing guarding it, so it never reaches a log."""
    return REPORT_LINK.sub(r"\1***", path)


HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",  # Google's button checks the page's origin from it
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin-allow-popups",  # Google's sign-in popup reports back to this page
}


def create_app() -> FastAPI:
    settings = get_settings()

    # No public docs or schema: the schema is written to openapi.json by `python -m app.cli openapi` instead.
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        stop = (
            radar_run.start_scheduler(session_factory(), settings, lambda: radar_run.default_tools(settings))
            if settings.radar_schedule
            else None
        )
        yield
        if stop is not None:
            stop.set()

    app = FastAPI(title="GTM Tracker", docs_url=None, openapi_url=None, redoc_url=None, lifespan=lifespan)
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
        if REPORT_LINK.match(
            request.url.path
        ):  # a shared report: kept out of search engines, its link out of referrers
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
            response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Request-Id"] = request_id
        log.info(
            "request",
            extra={
                "method": request.method,
                "path": log_path(request.url.path),  # never the query string, nor a report link's token
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

    @app.exception_handler(RuleError)
    def rule_broken(_request: Request, exc: RuleError) -> JSONResponse:
        code = 404 if isinstance(exc, NotFoundError) else 409
        return JSONResponse({"detail": str(exc)}, status_code=code)

    for module in (auth_routes, companies, people, moves, today, fractional, backup, radar, enrich, magnets):
        app.include_router(module.router)
    app.include_router(magnets.public)

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
