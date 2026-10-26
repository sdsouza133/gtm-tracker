"""Where a company is in the process, and what moves it.

Stages only move forward on their own (an email sent -> contacted, a reply -> replied, a call done -> call booked);
backwards only by hand. Parked, rejected and bench companies are out of play: their moves stay, but leave Today.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Move, MoveStatus, MoveType, ParkedWhy, Stage
from app.services import reach
from app.services.history import already_won, record

PROGRESS = (
    Stage.NOT_STARTED,
    Stage.RESEARCHING,
    Stage.CONTACTED,
    Stage.REPLIED,
    Stage.CALL_BOOKED,
    Stage.INTERVIEWING,
    Stage.TAKE_HOME,
    Stage.OFFER,
)
OUT_OF_PLAY = frozenset({Stage.PARKED, Stage.REJECTED, Stage.BENCH})
# One-off wins: reaching these stages earns XP once per company.
STAGE_XP = {Stage.CALL_BOOKED: 25, Stage.INTERVIEWING: 25, Stage.TAKE_HOME: 15, Stage.OFFER: 100}


def label(stage: Stage) -> str:
    return stage.value.replace("_", " ")


def _win(session: Session, company: Company, stage: Stage) -> tuple[int, str | None]:
    xp = STAGE_XP.get(stage, 0)
    if not xp:
        return 0, None
    tag = f"stage:{stage.value}"
    if already_won(session, company.id, tag):
        return 0, None
    return xp, tag


def advance(session: Session, company: Company | None, to: Stage) -> bool:
    """Move a company forward to `to` if it's in play and earlier than that."""
    if company is None or company.stage not in PROGRESS or to not in PROGRESS:
        return False
    if PROGRESS.index(company.stage) >= PROGRESS.index(to):
        return False
    company.stage = to
    xp, tag = _win(session, company, to)
    record(session, "stage", f"{company.name}: stage moved to {label(to)}", company_id=company.id, xp=xp, tag=tag)
    return True


def set_stage(session: Session, company: Company, to: Stage) -> None:
    """A move by hand (dragging on the board). Leaving Parked forgets why it was parked, so the radar won't bring back
    a company the user parked on purpose, or re-park one they took back."""
    old = company.stage
    if old == to:
        return
    company.stage = to
    if to is Stage.PARKED:
        company.parked_why = ParkedWhy.MANUAL
        company.parked_reason = None
    else:
        company.parked_why = None
        company.parked_reason = None
    xp, tag = _win(session, company, to)
    record(
        session,
        "stage",
        f"{company.name}: stage {label(old)} → {label(to)}",
        company_id=company.id,
        xp=xp,
        tag=tag,
    )


def engaged(session: Session, company_id: str) -> bool:
    """Anything done there: a move finished, or anyone reached."""
    rows = session.execute(select(Move.type, Move.status, Move.sequence).where(Move.company_id == company_id)).all()
    return any(
        status is MoveStatus.DONE or (kind is MoveType.REACH and reach.step_days(seq or {}))
        for kind, status, seq in rows
    )


def park_skipped(session: Session, company: Company | None, today: date) -> bool:
    """Skipping the application, before doing anything else there, passes on the company."""
    if company is None or company.stage is not Stage.NOT_STARTED or engaged(session, company.id):
        return False
    company.stage = Stage.PARKED
    company.parked_why = ParkedWhy.SKIPPED_APPLY
    company.parked_reason = (
        f"You skipped applying on {today:%b %-d}, so its people are off your list. "
        "Reopen the Apply move to bring it back."
    )
    record(session, "stage", f"{company.name}: parked, you skipped the application", company_id=company.id)
    return True


def unpark_skipped(session: Session, company: Company | None) -> bool:
    if company is None or company.stage is not Stage.PARKED or company.parked_why is not ParkedWhy.SKIPPED_APPLY:
        return False
    company.stage = Stage.NOT_STARTED
    company.parked_why = None
    company.parked_reason = None
    record(session, "stage", f"{company.name}: back from parked, you reopened the application", company_id=company.id)
    return True
