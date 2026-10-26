"""The Today list: what's due or overdue at companies still in play, grouped the way the day is worked, plus what's
already been done today and who you're waiting on."""

from dataclasses import dataclass
from datetime import date, datetime, time
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import Settings
from app.models import Company, Move, MoveStatus, MoveType, Sureness
from app.services import reach
from app.services.stages import OUT_OF_PLAY

WAITING_LIMIT = 50


class Group(StrEnum):
    CALLS = "calls"
    APPLY = "apply"
    REACH_OUT = "reach_out"
    FOLLOW_UP = "follow_up"
    PREP = "prep"


GROUP_LABELS = {
    Group.CALLS: "Interviews and calls",
    Group.APPLY: "Apply",
    Group.REACH_OUT: "Reach out: email and LinkedIn request",
    Group.FOLLOW_UP: "Follow up: LinkedIn message or bump",
    Group.PREP: "Research and prep",
}
_BY_TYPE = {
    MoveType.CALL: Group.CALLS,
    MoveType.INTERVIEW: Group.CALLS,
    MoveType.TAKE_HOME: Group.CALLS,
    MoveType.APPLY: Group.APPLY,
    MoveType.EMAIL: Group.REACH_OUT,
    MoveType.APPROVER_EMAIL: Group.REACH_OUT,
    MoveType.CONNECT: Group.REACH_OUT,
    MoveType.COMMENT: Group.REACH_OUT,
    MoveType.BUMP: Group.FOLLOW_UP,
    MoveType.LINKEDIN_DM: Group.FOLLOW_UP,
    MoveType.FOLLOW_UP: Group.FOLLOW_UP,
}
_ORDER = list(Group)
SURE_RANK = {Sureness.CONFIRMED: 0, Sureness.LIKELY: 1, Sureness.GUESS: 2, None: 3}


def group_of(move: Move) -> Group:
    if move.type is MoveType.REACH:
        nxt = str(move.sequence.get("next", ""))
        return Group.REACH_OUT if "email" in nxt or "request" in nxt else Group.FOLLOW_UP
    return _BY_TYPE.get(move.type, Group.PREP)


def _priority(move: Move) -> tuple[int, date, int, str, int, str]:
    company = move.company
    posted = company.posted.toordinal() if company and company.posted else 0
    return (
        _ORDER.index(group_of(move)),
        move.due,
        -posted,  # the newest role first
        move.company_id or "",  # keeps a company's people together
        SURE_RANK[move.person.sureness if move.person else None],
        move.id,
    )


def _in_play(company: Company | None) -> bool:
    return company is None or company.stage not in OUT_OF_PLAY


@dataclass(frozen=True)
class TodayList:
    groups: list[tuple[Group, list[Move]]]
    overdue: int
    done_today: list[Move]
    waiting: list[Move]
    waiting_total: int


def build(session: Session, settings: Settings, today: date) -> TodayList:
    load = (joinedload(Move.company), joinedload(Move.person))
    due = session.scalars(
        select(Move)
        .options(*load)
        .outerjoin(Company, Move.company_id == Company.id)
        .where(
            Move.status == MoveStatus.OPEN,
            Move.due <= today,
            (Company.id.is_(None)) | (Company.stage.not_in(OUT_OF_PLAY)),
        )
    ).all()
    due = sorted(due, key=_priority)
    groups = [(g, [m for m in due if group_of(m) is g]) for g in Group]

    start = datetime.combine(today, time.min, tzinfo=settings.tz)
    touched = session.scalars(select(Move).options(*load).where(Move.updated_at >= start)).all()
    done_today = [m for m in touched if _done_on(m, today, settings)]

    waiting_all = [
        m
        for m in session.scalars(
            select(Move)
            .options(*load)
            .where(Move.type == MoveType.REACH, Move.sequence["next"].as_string().in_(["waiting", "bump", "dm"]))
        ).all()
        if _in_play(m.company) and _waiting(m, today)
    ]
    waiting_all.sort(key=lambda m: (_first_touch(m) or today, m.id))
    return TodayList(
        groups=[(g, ms) for g, ms in groups if ms],
        overdue=sum(1 for m in due if m.due < today),
        done_today=done_today,
        waiting=waiting_all[:WAITING_LIMIT],
        waiting_total=len(waiting_all),
    )


def _done_on(move: Move, today: date, settings: Settings) -> bool:
    if move.type is MoveType.REACH:
        days = reach.step_days(move.sequence)
        return any(d == today for s, d in days.items() if s is not reach.Step.ACCEPTED)
    return (
        move.status is MoveStatus.DONE
        and move.done_at is not None
        and move.done_at.astimezone(settings.tz).date() == today
    )


def _first_touch(move: Move) -> date | None:
    days = reach.step_days(move.sequence)
    touches = [d for s, d in days.items() if s in reach.FIRST_TOUCHES]
    return min(touches) if touches else None


def _waiting(move: Move, today: date) -> bool:
    """Reached, no reply yet, and nothing due today."""
    if _first_touch(move) is None:
        return False
    return move.status is MoveStatus.DONE or move.due > today
