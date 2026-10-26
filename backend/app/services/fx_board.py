"""Reading and changing Fractional prospects. Lists stay light at any size: the rules run over each prospect's
small `mine` record, and full rows (with the research) are loaded only for the cards on screen."""

from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import ColumnElement, Text, cast, func, select
from sqlalchemy.orm import Session

from app.models import Prospect, Setting
from app.schemas import (
    BadgeOut,
    FollowUpOut,
    FxBoard,
    FxColumn,
    FxStats,
    HeatDay,
    LevelOut,
    ProspectCard,
    ProspectDetail,
    ProspectIn,
    ProspectPatch,
    ProspectPerson,
    Synced,
)
from app.services import fractional as fx
from app.services.history import record

COMING_UP = 12
COLUMN_ITEMS = 50
LIST_ITEMS = 50  # most cards in one list on the board; the totals say how many more there are
TOP_LEVEL = ("id", "day", "rank", "name", "domain", "fit")
PIPELINE = (
    (fx.Stage.UNTOUCHED, "Not reached yet"),
    (fx.Stage.WAITING, "Waiting on a reply"),
    (fx.Stage.TALKING, "Talking"),
    (fx.Stage.CALL, "Call booked"),
    (fx.Stage.PROPOSAL, "Proposal sent"),
    (fx.Stage.WON, "Clients"),
    (fx.Stage.CLOSED, "Skipped or lost"),
)
IN_PLAY = frozenset({fx.Stage.WAITING, fx.Stage.TALKING, fx.Stage.CALL, fx.Stage.PROPOSAL})
STEP_WORDS = {
    "researched": "dossier read",
    "fu1": "follow-up 1 sent",
    "fu2": "follow-up 2 sent",
    "replied": "they replied",
    "call": "call booked",
    "proposal": "proposal sent",
    "won": "signed as a client",
}
TOUCH_WORDS = {"connect": "LinkedIn request", "dm": "LinkedIn DM", "email": "email"}


@dataclass(frozen=True)
class Light:
    """The fields the rules need, without the research."""

    id: str
    day: date
    rank: int
    mine: dict[str, Any]


ORDER = (Prospect.effective_day, Prospect.rank, Prospect.id)
UNTOUCHED = Prospect.stage == fx.Stage.UNTOUCHED.value


def _acted_on(session: Session) -> list[Light]:
    """The prospects you've done something with. This grows with your own work, not with the research history."""
    rows = session.execute(
        select(Prospect.id, Prospect.day, Prospect.rank, Prospect.mine).where(
            (Prospect.xp > 0) | (Prospect.stage != fx.Stage.UNTOUCHED.value)
        )
    )
    return [Light(i, d, r, m or {}) for i, d, r, m in rows]


def _count(session: Session, *where: ColumnElement[bool]) -> int:
    return session.scalar(select(func.count()).select_from(Prospect).where(*where)) or 0


def _page(
    session: Session, today: date, *where: ColumnElement[bool], order: Any = ORDER, limit: int = LIST_ITEMS
) -> list[ProspectCard]:
    return [card(p, today) for p in session.scalars(select(Prospect).where(*where).order_by(*order).limit(limit))]


def goals(session: Session) -> dict[str, int]:
    row = session.get(Setting, "fx_goals")
    value = row.value if row and isinstance(row.value, dict) else {}
    return {"default": fx.DEFAULT_GOAL, **value}


def card(p: Prospect, today: date) -> ProspectCard:
    r, mine = p.research, p.mine or {}
    follow = fx.next_follow_up(mine)
    return ProspectCard(
        id=p.id,
        day=p.day,
        effective_day=fx.effective_day(p.day, mine),
        rank=p.rank,
        name=p.name,
        domain=p.domain,
        website=r.get("website"),
        round=r.get("round", ""),
        hq=r.get("hq", ""),
        employees=r.get("employees", ""),
        dmarc=r.get("dmarc", ""),
        one_liner=(r.get("research") or {}).get("one_liner", ""),
        why_now=r.get("why_now", ""),
        people=[ProspectPerson.model_validate(x) for x in r.get("people", [])],
        touched=sorted(k for k, kinds in (mine.get("touches") or {}).items() if kinds),
        status=mine.get("status") or "open",
        stage=fx.stage(mine).value,
        next_step=fx.next_step(mine, today),
        follow_up=FollowUpOut(step=follow.step, due=follow.due) if follow else None,
        first_touch=fx.first_touch(mine),
        xp=fx.xp(mine),
    )


def detail(p: Prospect, today: date) -> ProspectDetail:
    r, mine = p.research, p.mine or {}
    return ProspectDetail(
        **card(p, today).model_dump(),
        linkedin=r.get("linkedin"),
        spf=r.get("spf", ""),
        fit=p.fit,
        fit_reason=r.get("fit_reason", ""),
        offer=r.get("offer", ""),
        pvp=r.get("pvp", ""),
        research=r.get("research") or {},
        touches=mine.get("touches") or {},
        steps=mine.get("steps") or {},
        lost_reason=mine.get("lost_reason", ""),
        my_notes=mine.get("my_notes", ""),
        draft=mine.get("draft", ""),
        day_override=mine.get("day_override"),
    )


def stats(session: Session, goal_map: dict[str, int], today: date) -> FxStats:
    lights = _acted_on(session)
    hits: Counter[date] = Counter(t for x in lights if (t := fx.first_touch(x.mine)))
    start = session.scalar(select(func.min(Prospect.day)))
    run = fx.streak(hits, goal_map, start, today)
    total_xp = sum(fx.xp(x.mine) for x in lights)
    level = fx.level_for(total_xp)
    stages = Counter(fx.stage(x.mine) for x in lights)
    monday = today - timedelta(days=today.weekday())
    first_day = monday - timedelta(weeks=fx.HEAT_WEEKS - 1)
    heat = [
        HeatDay(day=d, hits=hits.get(d, 0), goal=fx.goal_for(d, goal_map))
        for d in (first_day + timedelta(days=i) for i in range(fx.HEAT_WEEKS * 7))
        if d.weekday() < 5  # noqa: PLR2004  (Monday to Friday)
    ]
    reached = sum(1 for x in lights if fx.first_touch(x.mine))
    ever = {s: sum(1 for x in lights if fx.step_day(x.mine, s)) for s in ("replied", "call", "proposal")}
    clients = stages[fx.Stage.WON]
    return FxStats(
        xp=total_xp,
        level=LevelOut(**level.__dict__),
        streak=run.current,
        best_streak=run.best,
        heat=heat,
        clients=clients,
        monthly_revenue=clients * fx.CLIENT_MONTHLY_USD,
        revenue_goal=fx.REVENUE_GOAL_USD,
        funnel={"reached": reached, **ever, "clients": clients},
        badges=[BadgeOut(**b.__dict__) for b in fx.badges((x.mine for x in lights), hits, run.best)],
    )


def board(session: Session, today: date) -> FxBoard:
    goal_map = goals(session)
    due = (Prospect.follow_up_due <= today,)
    carried = (UNTOUCHED, Prospect.effective_day < today)
    upcoming = (UNTOUCHED, Prospect.effective_day > today)
    return FxBoard(
        today=today,
        goal=fx.goal_for(today, goal_map),
        hits_today=_count(session, Prospect.first_touch == today),
        follow_ups_due=_page(session, today, *due, order=(Prospect.follow_up_due, Prospect.rank, Prospect.id)),
        follow_ups_due_total=_count(session, *due),
        follow_ups_later=_count(session, Prospect.follow_up_due > today),
        carried_over=_page(session, today, *carried),
        carried_over_total=_count(session, *carried),
        todays_list=_page(session, today, UNTOUCHED, Prospect.effective_day == today),
        reached_today=_page(session, today, Prospect.first_touch == today, order=(Prospect.rank, Prospect.id)),
        coming_up=_page(session, today, *upcoming, limit=COMING_UP),
        coming_up_total=_count(session, *upcoming),
        stats=stats(session, goal_map, today),
    )


def pipeline(session: Session, today: date) -> list[FxColumn]:
    totals = dict(session.execute(select(Prospect.stage, func.count()).group_by(Prospect.stage)).all())
    return [
        FxColumn(
            key=key.value,
            label=label,
            total=totals.get(key.value, 0),
            items=_page(session, today, Prospect.stage == key.value, limit=COLUMN_ITEMS),
        )
        for key, label in PIPELINE
    ]


SHOW = {
    "all": None,
    "untouched": frozenset({fx.Stage.UNTOUCHED}),
    "in_play": IN_PLAY,
    "closed": frozenset({fx.Stage.WON, fx.Stage.CLOSED}),
}


def search(
    session: Session, today: date, *, q: str | None, show: str, limit: int, offset: int
) -> tuple[list[ProspectCard], int]:
    where: list[ColumnElement[bool]] = []
    if q:
        like = f"%{q.strip().replace('%', r'\%').replace('_', r'\_')}%"
        # name, domain, what they do and the people's names all live in the row; search them as text
        where.append(
            Prospect.name.ilike(like) | Prospect.domain.ilike(like) | cast(Prospect.research, Text).ilike(like)
        )
    if (wanted := SHOW[show]) is not None:
        where.append(Prospect.stage.in_([s.value for s in wanted]))
    rows = session.scalars(select(Prospect).where(*where).order_by(*ORDER).limit(limit).offset(offset))
    return [card(p, today) for p in rows], _count(session, *where)


def sync(session: Session, prospects: list[ProspectIn]) -> Synced:
    """Research follows the daily list; what you did is never touched. Prospects are never deleted."""
    added = updated = 0
    existing = {p.id: p for p in session.scalars(select(Prospect).where(Prospect.id.in_([x.id for x in prospects])))}
    for item in prospects:
        data = item.model_dump(mode="json")
        fields = {k: data.pop(k) for k in TOP_LEVEL}
        row = existing.get(item.id)
        if row is None:
            session.add(Prospect(**fields, research=data, mine={"status": "open"}))
            added += 1
        elif row.research != data or any(getattr(row, k) != getattr(item, k) for k in TOP_LEVEL):
            for k in TOP_LEVEL[1:]:
                setattr(row, k, getattr(item, k))
            row.research = data
            updated += 1
    if added:
        record(session, "fractional", f"Fractional list: {added} new prospect{'s' if added != 1 else ''}")
    return Synced(added=added, updated=updated)


def change(session: Session, p: Prospect, body: ProspectPatch, today: date) -> list[str]:
    """Apply a change; returns what happened, in words, for the history."""
    when = body.when or today
    if when > today:
        raise fx.FractionalError("A tick can't be in the future.")
    mine = dict(p.mine or {})
    notes: list[str] = []
    people = {x["key"]: x for x in p.research.get("people", [])}
    if body.touch:
        t = body.touch
        fx.set_touch(mine, set(people), t.person, t.kind, t.on, when)
        if t.on:
            notes.append(f"{p.name}: {TOUCH_WORDS[t.kind]} sent to {people.get(t.person, {}).get('name', t.person)}")
    if body.step:
        fx.set_step(mine, body.step.name, body.step.on, when)
        if body.step.on:
            notes.append(f"{p.name}: {STEP_WORDS[body.step.name]}")
    if body.lost_reason is not None:
        mine["lost_reason"] = body.lost_reason
    if body.status is not None:
        fx.set_status(mine, body.status, when)
        if body.status != "open":
            notes.append(f"{p.name}: marked {body.status}")
    for key in ("my_notes", "draft"):
        if (value := getattr(body, key)) is not None:
            mine[key] = value
    if "day_override" in body.model_fields_set:
        mine["day_override"] = body.day_override.isoformat() if body.day_override else None
    p.mine = mine
    for note in notes:
        record(session, "fractional", note)
    return notes
