"""Today, the plan ahead, progress, the history, and settings."""

from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.auth import AppSettings, DbSession, SignedIn
from app.clock import Today
from app.models import Activity, Company, Move, MoveStatus, Setting
from app.schemas import (
    ActivityOut,
    DayCount,
    MoveCard,
    NoteCreate,
    Page,
    PlanDay,
    SettingsOut,
    StatsOut,
    TodayGroup,
    TodayOut,
)
from app.services import stats as stats_service
from app.services import today as today_service
from app.services.history import record
from app.services.stages import OUT_OF_PLAY

router = APIRouter(prefix="/api", tags=["today"], dependencies=[SignedIn])

PLAN_MAX_DAYS = 62


@router.get("/today")
def today_list(session: DbSession, settings: AppSettings, today: Today) -> TodayOut:
    built = today_service.build(session, settings, today)

    def cards(moves: list[Move]) -> list[MoveCard]:
        return [MoveCard.model_validate(m) for m in moves]

    return TodayOut(
        today=today,
        groups=[
            TodayGroup(key=g.value, label=today_service.GROUP_LABELS[g], moves=cards(moves))
            for g, moves in built.groups
        ],
        overdue=built.overdue,
        done_today=cards(built.done_today),
        waiting=cards(built.waiting),
        waiting_total=built.waiting_total,
    )


@router.get("/stats")
def stats(session: DbSession, settings: AppSettings, today: Today) -> StatsOut:
    s = stats_service.compute(session, settings, today)
    return StatsOut(
        xp=s.xp,
        level=s.level.number,
        level_title=s.level.title,
        level_floor_xp=s.level.floor_xp,
        next_level_xp=s.level.next_xp,
        streak=s.streak,
        best_streak=s.best_streak,
        streak_min=stats_service.STREAK_MIN,
        today_moves=s.today_moves,
        recent=[DayCount(day=d, moves=n) for d, n in s.recent],
        funnel=s.funnel,
        in_play=s.in_play,
        days_left=s.days_left,
    )


@router.get("/plan")
def plan(
    session: DbSession,
    today: Today,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
) -> list[PlanDay]:
    """Open moves by day, from `from` (today) to `to` (two weeks on), at companies still in play."""
    start = start or today
    end = end or start + timedelta(days=13)
    if end < start or (end - start).days > PLAN_MAX_DAYS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Pick a range of up to {PLAN_MAX_DAYS} days.")
    rows = session.scalars(
        select(Move)
        .options(joinedload(Move.company), joinedload(Move.person))
        .outerjoin(Company, Move.company_id == Company.id)
        .where(
            Move.status == MoveStatus.OPEN,
            Move.due >= start,
            Move.due <= end,
            (Company.id.is_(None)) | (Company.stage.not_in(OUT_OF_PLAY)),
        )
        .order_by(Move.due, Move.company_id, Move.id)
    ).all()
    days: dict[date, list[MoveCard]] = {}
    for m in rows:
        days.setdefault(m.due, []).append(MoveCard.model_validate(m))
    return [PlanDay(day=d, moves=ms) for d, ms in days.items()]


@router.get("/activity")
def activity(
    session: DbSession,
    company_id: Annotated[str | None, Query(max_length=40)] = None,
    before: Annotated[int | None, Query(ge=1, description="Return lines older than this id")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page[ActivityOut]:
    """The history, newest first. Page back with `before` = the last id you have."""
    query = select(Activity)
    if company_id:
        query = query.where(Activity.company_id == company_id)
    if before:
        query = query.where(Activity.id < before)
    rows = session.scalars(query.order_by(Activity.id.desc()).limit(limit + 1)).all()
    return Page(items=[ActivityOut.model_validate(a) for a in rows[:limit]], total=len(rows))


@router.post("/activity", status_code=status.HTTP_201_CREATED)
def add_note(body: NoteCreate, session: DbSession) -> ActivityOut:
    row = record(session, "note", body.text.strip(), company_id=body.company_id, person_id=body.person_id)
    session.commit()
    return ActivityOut.model_validate(row)


def _read_settings(session: DbSession) -> SettingsOut:
    names = set(SettingsOut.model_fields)
    values: dict[str, Any] = {
        row.key: row.value for row in session.scalars(select(Setting).where(Setting.key.in_(names)))
    }
    return SettingsOut.model_validate(values)


@router.get("/settings")
def get_settings_route(session: DbSession) -> SettingsOut:
    return _read_settings(session)


@router.patch("/settings")
def update_settings(body: SettingsOut, session: DbSession) -> SettingsOut:
    """Change the named settings; the rest stay as they are."""
    for key, value in body.model_dump(mode="json", exclude_unset=True).items():
        row = session.get(Setting, key)
        if row is None:
            session.add(Setting(key=key, value=value))
        else:
            row.value = value
    session.commit()
    return _read_settings(session)
