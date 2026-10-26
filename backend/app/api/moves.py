"""Moves: adding one, ticking a reach-out's steps, finishing, skipping, rescheduling, pulling work forward."""

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.auth import DbSession, SignedIn
from app.clock import Today
from app.models import Move
from app.schemas import Cleared, MoveCard, MoveCreate, MoveOut, MovePatch, Pull, Pulled, StepTick
from app.services import today as today_service
from app.services.outreach import MoveChange, NewMove, add_move, change_move, delete_move, pull_forward, tick_step

router = APIRouter(prefix="/api/moves", tags=["moves"], dependencies=[SignedIn])


def get_move(session: Session, move_id: str) -> Move:
    move = session.get(Move, move_id)
    if move is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That move isn't in the tracker.")
    return move


@router.post("", status_code=status.HTTP_201_CREATED)
def create(body: MoveCreate, session: DbSession, today: Today) -> MoveCard:
    move = add_move(session, NewMove(**{**body.model_dump(), "due": body.due or today}))
    session.commit()
    return MoveCard.model_validate(move)


@router.patch("/{move_id}")
def update(move_id: str, body: MovePatch, session: DbSession, today: Today) -> MoveCard:
    """Change the title, notes or link; finish, skip or reopen it; or move it to another day. On a reach-out, a new
    day before the first touches moves Day 0, and after them holds the follow-up until then."""
    move = get_move(session, move_id)
    fields = body.model_dump(exclude_unset=True)
    if "url" in fields and fields["url"] is None:
        fields["url"] = ""
    change_move(session, move, MoveChange(**fields), today)
    session.commit()
    return MoveCard.model_validate(move)


@router.post("/{move_id}/steps")
def step(move_id: str, body: StepTick, session: DbSession, today: Today) -> MoveCard:
    """Tick one step of a reach-out: done today (or on a day), n/a, or not done."""
    move = get_move(session, move_id)
    value = today if body.value == "today" else body.value
    tick_step(session, move, body.step, value, today)
    session.commit()
    return MoveCard.model_validate(move)


@router.delete("/{move_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove(move_id: str, session: DbSession) -> Response:
    delete_move(session, get_move(session, move_id))
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/pull")
def pull(body: Pull, session: DbSession, today: Today) -> Pulled:
    """Bring the next few moves to today, when today's list is done."""
    pulled = pull_forward(session, body.n, today)
    session.commit()
    return Pulled(pulled=[MoveOut.model_validate(m) for m in pulled])


@router.post("/clear-backlog")
def clear_backlog(session: DbSession, today: Today) -> Cleared:
    """Skip every open move overdue by more than a week, so Today starts fresh."""
    cleared = today_service.clear_stale(session, today)
    session.commit()
    return Cleared(cleared=cleared)
