"""XP, streak and level, worked out on the server from the whole history (not the last page of it).

Moves earn XP while they're done: ticking a step earns it, unticking takes it back. One-off wins (a reply, a call
booked, an offer) carry their XP on the history line, once per company. A day counts toward the streak when at least
three moves were done that day.
"""

import math
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.clock import local_day
from app.config import Settings
from app.models import Activity, Company, Move, MoveStatus, MoveType, Setting, Stage
from app.services import reach
from app.services.stages import PROGRESS

MOVE_XP: dict[MoveType, int] = {
    MoveType.REACH: 0,  # its steps earn instead
    MoveType.COMMENT: 1,
    MoveType.CONNECT: 1,
    MoveType.APPLY: 3,
    MoveType.EMAIL: 3,
    MoveType.APPROVER_EMAIL: 3,
    MoveType.BUMP: 2,
    MoveType.LINKEDIN_DM: 1,
    MoveType.CALL: 5,
    MoveType.INTERVIEW: 5,
    MoveType.TAKE_HOME: 5,
    MoveType.FOLLOW_UP: 1,
    MoveType.RESEARCH: 2,
    MoveType.PREP: 5,
    MoveType.BUILD: 8,
    MoveType.POST: 3,
    MoveType.REVIEW: 2,
    MoveType.CUSTOM: 2,
}
STEP_XP = {reach.Step.EMAIL: 3, reach.Step.REQUEST: 1, reach.Step.ACCEPTED: 1, reach.Step.DM: 2, reach.Step.BUMP: 2}
DAY_BLOCK_XP = 5
STREAK_MIN = 3
LEVEL_TITLES = ("Warming up", "Sending", "Getting replies", "Booking calls", "Interviewing", "Closing")
XP_PER_LEVEL = 40
FUNNEL = (Stage.CONTACTED, Stage.REPLIED, Stage.CALL_BOOKED, Stage.OFFER)
RECENT_DAYS = 14


@dataclass(frozen=True)
class Level:
    number: int
    title: str
    floor_xp: int
    next_xp: int


def level_for(xp: int) -> Level:
    n = math.floor(math.sqrt(max(xp, 0) / XP_PER_LEVEL)) + 1
    return Level(
        number=n,
        title=LEVEL_TITLES[min(n, len(LEVEL_TITLES)) - 1],
        floor_xp=XP_PER_LEVEL * (n - 1) ** 2,
        next_xp=XP_PER_LEVEL * n**2,
    )


def streaks(per_day: Counter[date], today: date) -> tuple[int, int]:
    """(current, best): runs of consecutive days with at least STREAK_MIN moves. Today still counts as in progress,
    so the current streak runs back from yesterday until today reaches the minimum."""
    good = {d for d, n in per_day.items() if n >= STREAK_MIN}
    day = today if today in good else today - timedelta(days=1)
    current = 0
    while day in good:
        current += 1
        day -= timedelta(days=1)
    best = 0
    for d in good:
        if d - timedelta(days=1) not in good:
            length = 1
            while d + timedelta(days=length) in good:
                length += 1
            best = max(best, length)
    return current, best


@dataclass(frozen=True)
class Stats:
    xp: int
    level: Level
    streak: int
    best_streak: int
    today_moves: int
    recent: list[tuple[date, int]]
    funnel: dict[str, int]
    in_play: int
    days_left: int | None


def moves_by_day(session: Session, settings: Settings) -> tuple[int, Counter[date]]:
    """XP earned by moves, and how many moves were done each day."""
    xp = 0
    per_day: Counter[date] = Counter()
    rows = session.execute(
        select(Move.type, Move.status, Move.done_at, Move.sequence).where(
            or_(Move.type == MoveType.REACH, Move.status == MoveStatus.DONE)
        )
    )
    for kind, status, done_at, seq in rows:
        if kind is MoveType.REACH:
            for step, day in reach.step_days(seq or {}).items():
                xp += STEP_XP[step]
                if step is not reach.Step.ACCEPTED:
                    per_day[day] += 1
        elif status is MoveStatus.DONE and done_at is not None:
            xp += MOVE_XP.get(kind, 2)
            per_day[local_day(done_at, settings)] += 1
    return xp, per_day


def compute(session: Session, settings: Settings, today: date) -> Stats:
    move_xp, per_day = moves_by_day(session, settings)
    wins = session.scalar(select(func.coalesce(func.sum(Activity.xp), 0))) or 0
    days: dict[str, dict[str, bool]] = _setting(session, "days") or {}
    blocks = sum(1 for marks in days.values() if isinstance(marks, dict) for done in marks.values() if done is True)
    xp = move_xp + int(wins) + blocks * DAY_BLOCK_XP
    current, best = streaks(per_day, today)

    stage_counts = Counter(dict(session.execute(select(Company.stage, func.count()).group_by(Company.stage)).all()))
    funnel = {
        s.value: sum(n for stage, n in stage_counts.items() if stage in PROGRESS and _at_or_past(stage, s))
        for s in FUNNEL
    }
    in_play = sum(n for stage, n in stage_counts.items() if stage in PROGRESS)
    deadline = _setting(session, "deadline")
    days_left = (date.fromisoformat(deadline) - today).days if isinstance(deadline, str) and deadline else None
    recent = [(today - timedelta(days=i), per_day.get(today - timedelta(days=i), 0)) for i in range(RECENT_DAYS)]
    return Stats(
        xp=xp,
        level=level_for(xp),
        streak=current,
        best_streak=best,
        today_moves=per_day.get(today, 0),
        recent=list(reversed(recent)),
        funnel=funnel,
        in_play=in_play,
        days_left=days_left,
    )


def _at_or_past(stage: Stage, mark: Stage) -> bool:
    return PROGRESS.index(stage) >= PROGRESS.index(mark)


def _setting(session: Session, key: str) -> Any:
    row = session.get(Setting, key)
    return row.value if row else None
