"""Download a full backup, and load one into an empty tracker."""

from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, status
from fastapi.responses import StreamingResponse

from app.auth import DbSession, SignedIn
from app.backup import RestoreRefusedError, restore, stream
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


@router.post("/restore")
def restore_backup(session: DbSession, backup: Annotated[dict[str, Any], Body()]) -> dict[str, int]:
    """Load a backup (from Download backup) into an empty tracker: the same as `python -m app.cli restore`, for a
    server whose database can only be reached through the app. A tracker that has any data refuses (409)."""
    try:
        return restore(session, backup)
    except RestoreRefusedError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
