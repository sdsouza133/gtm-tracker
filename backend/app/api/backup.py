"""Download a full backup."""

from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.auth import DbSession, SignedIn
from app.backup import stream
from app.clock import Today

router = APIRouter(prefix="/api", tags=["backup"], dependencies=[SignedIn])


BACKUP_JSON: dict[int | str, dict[str, Any]] = {
    200: {"content": {"application/json": {"schema": {"type": "object"}}}, "description": "The backup"}
}


@router.get("/export", response_class=StreamingResponse, responses=BACKUP_JSON)
def export(session: DbSession, today: Today) -> StreamingResponse:
    """Everything in the tracker as one JSON file. Restore it with `python -m app.cli restore <file>`."""
    return StreamingResponse(
        stream(session),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="gtm-tracker-{today}.json"'},
    )
