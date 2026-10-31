"""The Today list: what's due at companies still in play, grouped the way the day is worked, plus what's already
been done today and who you're waiting on. It stays small on purpose: only the last week's moves, and no more than a
day's worth."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum

from sqlalchemy import select, update
from sqlalchemy.orm import Session, joinedload, selectinload

from app.config import Settings
from app.models import Company, Move, MoveStatus, MoveType, Person, PersonStatus, Stage, Sureness
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


def _priority(move: Move) -> tuple[int, int, date, str, int, str]:
    company = move.company
    posted = company.posted.toordinal() if company and company.posted else 0
    return (
        _ORDER.index(group_of(move)),
        -posted,  # the newest role first: a posting loses value by the day
        move.due,
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
    loved: list[Company]  # jobs you marked "I love it", newest mark first


def build(session: Session, settings: Settings, today: date, show_all: bool = False) -> TodayList:
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

    # a call or interview held today doesn't use up a company slot
    started = {m.company_id for m in done_today if m.company_id and group_of(m) is not Group.CALLS}
    loved = loved_companies(session)
    loved_ids = {c.id for c in loved}
    due, more = _days_worth(
        sorted(due, key=_priority), started - loved_ids, None if show_all else DAILY_COMPANIES, loved_ids
    )
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
        loved=loved,
        looms=list(
            session.scalars(
                select(Person)
                .options(joinedload(Person.company))
                .where(Person.details["loom"].as_string() == "asked")
                .order_by(Person.updated_at)
            )
        ),
    )


def _days_worth(
    ordered: list[Move], started: set[str], limit: int | None, loved: frozenset[str] | set[str] = frozenset()
) -> tuple[list[Move], int]:
    """Whole companies, most important first, up to the day's limit (None: no limit); a company already worked on
    today stays and counts toward it. Calls, moves with no company and jobs you love always show, without using a
    slot. Returns the moves and how many companies wait."""
    slots = len(ordered) if limit is None else max(0, limit - len(started))
    chosen: set[str] = set()
    waiting: set[str] = set()
    shown: list[Move] = []
    for m in ordered:
        cid = m.company_id
        if cid is None or cid in started or cid in chosen or cid in loved or group_of(m) is Group.CALLS:
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


def loved_companies(session: Session) -> list[Company]:
    """Jobs you marked "I love it" and haven't been turned down for, newest mark first."""
    rows = session.scalars(
        select(Company)
        .options(selectinload(Company.people), selectinload(Company.moves))
        .where(Company.research["loved"].as_string().is_not(None), Company.stage != Stage.REJECTED)
    ).all()
    return sorted((c for c in rows if c.loved), key=lambda c: (c.loved or "", c.id), reverse=True)


@dataclass(frozen=True)
class LovedPersonView:
    id: str
    name: str
    title: str
    has_email: bool
    linkedin: str | None
    email_sent: str | None
    linkedin_sent: str | None
    replied: bool
    next: str | None
    due: date | None


def loved_view(company: Company) -> tuple[bool, list[LovedPersonView], date | None]:
    """For a job you love: whether you applied, each person's email and LinkedIn ticks, and the next follow-up."""
    reach_by_person: dict[str, Move] = {}
    for m in sorted(company.moves, key=lambda m: m.status is MoveStatus.OPEN):  # an open reach-out wins
        if m.type is MoveType.REACH and m.person_id:
            reach_by_person[m.person_id] = m
    people = []
    for p in sorted(company.people, key=lambda p: (p.left, p.name)):
        if p.left:
            continue
        r = reach_by_person.get(p.id)
        seq = (r.sequence or {}) if r else {}
        steps = seq.get("steps", {})
        is_open = r is not None and r.status is MoveStatus.OPEN
        people.append(
            LovedPersonView(
                id=p.id,
                name=p.name,
                title=p.title,
                has_email=bool(p.email),
                linkedin=p.linkedin,
                email_sent=_tick(steps.get(reach.Step.EMAIL)),
                linkedin_sent=_tick(steps.get(reach.Step.REQUEST)),
                replied=p.status is PersonStatus.REPLIED,
                next=(str(seq.get("next") or "") or None) if is_open else None,
                due=r.due if r is not None and is_open else None,
            )
        )
    applied = any(m.type is MoveType.APPLY and m.status is MoveStatus.DONE for m in company.moves)
    open_dues = [m.due for m in company.moves if m.status is MoveStatus.OPEN]
    return applied, people, min(open_dues) if open_dues else None


def _tick(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
