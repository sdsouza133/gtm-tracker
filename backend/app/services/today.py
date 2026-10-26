"""The Today list: what's due at companies still in play, grouped the way the day is worked, plus what's already
been done today and who you're waiting on. It stays small on purpose: only the last week's moves, and no more than a
day's worth."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum

from sqlalchemy import select, update
from sqlalchemy.orm import Session, joinedload

from app.config import Settings
from app.models import Company, Move, MoveStatus, MoveType, Person, Sureness
from app.services import reach
from app.services.history import record
from app.services.stages import OUT_OF_PLAY

WAITING_LIMIT = 50
FRESH_DAYS = 7  # a move overdue by more than this has gone stale and drops off; an unstarted reach-out doesn't
DAILY_COMPANIES = 5  # companies a day, counting the ones already worked on today; calls and loose tasks always show
FIRST_TOUCH_DUE = ("email+request", "email", "request")


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
    more: int  # companies held back for another day by the daily limit
    done_today: list[Move]
    waiting: list[Move]
    waiting_total: int
    looms: list[Person]  # asked for a Loom video that hasn't been sent yet


def build(session: Session, settings: Settings, today: date) -> TodayList:
    load = (joinedload(Move.company), joinedload(Move.person))
    due = session.scalars(
        select(Move)
        .options(*load)
        .outerjoin(Company, Move.company_id == Company.id)
        .where(
            Move.status == MoveStatus.OPEN,
            Move.due <= today,
            # a reach-out stays until both the email and the LinkedIn request are sent, or it's skipped
            (Move.due >= today - timedelta(days=FRESH_DAYS))
            | (Move.type == MoveType.REACH) & Move.sequence["next"].as_string().in_(FIRST_TOUCH_DUE),
            (Company.id.is_(None)) | (Company.stage.not_in(OUT_OF_PLAY)),
        )
    ).all()

    start = datetime.combine(today, time.min, tzinfo=settings.tz)
    touched = session.scalars(select(Move).options(*load).where(Move.updated_at >= start)).all()
    done_today = [m for m in touched if _done_on(m, today, settings)]

    due, more = _days_worth(sorted(due, key=_priority), {m.company_id for m in done_today if m.company_id})
    groups = [(g, [m for m in due if group_of(m) is g]) for g in Group]

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
        more=more,
        done_today=done_today,
        waiting=waiting_all[:WAITING_LIMIT],
        waiting_total=len(waiting_all),
        looms=list(
            session.scalars(
                select(Person)
                .options(joinedload(Person.company))
                .where(Person.details["loom"].as_string() == "asked")
                .order_by(Person.updated_at)
            )
        ),
    )


def _days_worth(ordered: list[Move], started: set[str]) -> tuple[list[Move], int]:
    """Whole companies, most important first, up to the day's limit; a company already worked on today stays and
    counts toward it. Calls and moves with no company always show. Returns the moves and how many companies wait."""
    slots = max(0, DAILY_COMPANIES - len(started))
    chosen: set[str] = set()
    waiting: set[str] = set()
    shown: list[Move] = []
    for m in ordered:
        cid = m.company_id
        if cid is None or cid in started or cid in chosen or group_of(m) is Group.CALLS:
            shown.append(m)
        elif len(chosen) < slots:
            chosen.add(cid)
            shown.append(m)
        else:
            waiting.add(cid)
    return shown, len(waiting)


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


def clear_stale(session: Session, today: date) -> int:
    """Skip every open move overdue by more than FRESH_DAYS: the backlog that would only weigh on the list. One history
    line for the lot, not one per move. Returns how many were cleared."""
    cutoff = today - timedelta(days=FRESH_DAYS)
    stale = select(Move.id).where(Move.status == MoveStatus.OPEN, Move.due < cutoff)
    ids = list(session.scalars(stale))
    if ids:
        session.execute(
            update(Move).where(Move.id.in_(ids)).values(status=MoveStatus.SKIPPED, skip_reason="Old backlog, cleared"),
            execution_options={"synchronize_session": False},
        )
        record(session, "skipped", f"Cleared {len(ids)} old moves due before {cutoff:%b %-d}")
    return len(ids)
