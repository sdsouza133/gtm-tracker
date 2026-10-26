"""Fractional outreach: today's list, the pipeline, every prospect, and the daily sync from research."""

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status

from app.auth import DbSession, SignedIn
from app.clock import Today
from app.models import Prospect
from app.schemas import FxBoard, FxColumn, Page, ProspectCard, ProspectDetail, ProspectPatch, ProspectSync, Synced
from app.services import fx_board
from app.services.fractional import FractionalError

router = APIRouter(prefix="/api/fx", tags=["fractional"], dependencies=[SignedIn])


def get_prospect(session: DbSession, prospect_id: str) -> Prospect:
    p = session.get(Prospect, prospect_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That prospect isn't in the list.")
    return p


@router.get("/board")
def board(session: DbSession, today: Today) -> FxBoard:
    """Today: follow-ups due, carried over, today's list, reached today, coming up, and progress."""
    return fx_board.board(session, today)


@router.get("/pipeline")
def pipeline(session: DbSession, today: Today) -> list[FxColumn]:
    return fx_board.pipeline(session, today)


@router.get("/prospects")
def prospects(
    session: DbSession,
    today: Today,
    q: Annotated[str | None, Query(max_length=100)] = None,
    show: Literal["all", "untouched", "in_play", "closed"] = "all",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ProspectCard]:
    items, total = fx_board.search(session, today, q=q, show=show, limit=limit, offset=offset)
    return Page(items=items, total=total)


@router.get("/prospects/{prospect_id}")
def one(prospect_id: str, session: DbSession, today: Today) -> ProspectDetail:
    return fx_board.detail(get_prospect(session, prospect_id), today)


@router.patch("/prospects/{prospect_id}")
def update(prospect_id: str, body: ProspectPatch, session: DbSession, today: Today) -> ProspectDetail:
    """Tick a message or a step, close or reopen, move it to another day, or save notes and the draft. Several can go
    in one change (marking it lost with the reason, for example)."""
    p = get_prospect(session, prospect_id)
    try:
        fx_board.change(session, p, body, today)
    except FractionalError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    session.commit()
    return fx_board.detail(p, today)


@router.put("/prospects")
def sync(body: ProspectSync, session: DbSession) -> Synced:
    """For the daily research: add new prospects and refresh the research of known ones."""
    result = fx_board.sync(session, body.prospects)
    session.commit()
    return result
