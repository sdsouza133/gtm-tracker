"""Fractional outreach: a daily list of funded startups to pitch, worked person by person.

A prospect's research comes from automation and is replaced on every sync; what the user did lives in `mine` and is
never touched by a sync:

    touches   {person key: {connect|dm|email: day}}   the messages sent, first tick wins
    steps     {researched|fu1|fu2|replied|call|proposal|won: day}
    status    open | won | lost | skipped
    lost_reason, my_notes, draft, day_override

A **hit** is a prospect's first message: the day of its earliest touch. The daily goal counts hits. These functions are
pure; the API loads what they need and hands it over.
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from typing import Any

from app.clock import add_business_days, is_weekday, next_weekday

TOUCH_KINDS = ("connect", "dm", "email")
STEPS = ("researched", "fu1", "fu2", "replied", "call", "proposal", "won")
STATUSES = ("open", "won", "lost", "skipped")
TOUCH_XP = {"connect": 2, "dm": 3, "email": 3}
STEP_XP = {"researched": 2, "fu1": 2, "fu2": 2, "replied": 10, "call": 25, "proposal": 40, "won": 100}
FIRST_FOLLOW_UP_DAYS = 3  # working days after the first message
SECOND_FOLLOW_UP_DAYS = 4  # working days after the first follow-up
DEFAULT_GOAL = 10
CLIENT_MONTHLY_USD = 3000
REVENUE_GOAL_USD = 12000
LEVELS = (
    (0, "Rookie"),
    (50, "Prospector"),
    (120, "Opener"),
    (220, "Connector"),
    (350, "Pipeline builder"),
    (520, "Rainmaker"),
    (750, "Closer"),
    (1050, "Operator"),
    (1400, "Agency in the making"),
    (1800, "Fractional pro"),
)
HEAT_WEEKS = 4


class Stage(StrEnum):
    UNTOUCHED = "untouched"
    WAITING = "waiting"
    TALKING = "talking"
    CALL = "call"
    PROPOSAL = "proposal"
    WON = "won"
    CLOSED = "closed"


def _day(value: Any) -> date | None:
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def effective_day(day: date, mine: dict[str, Any]) -> date:
    return _day(mine.get("day_override")) or day


def touch_days(mine: dict[str, Any]) -> list[date]:
    touches: dict[str, dict[str, str]] = mine.get("touches") or {}
    return [d for kinds in touches.values() for d in (_day(v) for v in kinds.values()) if d]


def first_touch(mine: dict[str, Any]) -> date | None:
    days = touch_days(mine)
    return min(days) if days else None


def step_day(mine: dict[str, Any], step: str) -> date | None:
    return _day((mine.get("steps") or {}).get(step))


def stage(mine: dict[str, Any]) -> Stage:
    status = mine.get("status") or "open"
    if status == "won" or step_day(mine, "won"):
        return Stage.WON
    if status in ("lost", "skipped"):
        return Stage.CLOSED
    for step, result in (("proposal", Stage.PROPOSAL), ("call", Stage.CALL), ("replied", Stage.TALKING)):
        if step_day(mine, step):
            return result
    return Stage.WAITING if first_touch(mine) else Stage.UNTOUCHED


@dataclass(frozen=True)
class FollowUp:
    step: str  # fu1 or fu2
    due: date


def next_follow_up(mine: dict[str, Any]) -> FollowUp | None:
    """While they haven't replied: follow-up 1 three working days after the first message, follow-up 2 four working
    days after follow-up 1, then it rests."""
    first = first_touch(mine)
    if first is None or stage(mine) is not Stage.WAITING:
        return None
    fu1 = step_day(mine, "fu1")
    if fu1 is None:
        return FollowUp("fu1", add_business_days(first, FIRST_FOLLOW_UP_DAYS))
    if step_day(mine, "fu2") is None:
        return FollowUp("fu2", add_business_days(fu1, SECOND_FOLLOW_UP_DAYS))
    return None


def xp(mine: dict[str, Any]) -> int:
    touches: dict[str, dict[str, str]] = mine.get("touches") or {}
    total = sum(TOUCH_XP.get(kind, 0) for kinds in touches.values() for kind, v in kinds.items() if _day(v))
    return total + sum(STEP_XP[s] for s in STEPS if step_day(mine, s))


NEXT_STEP = {
    Stage.WON: "Client signed",
    Stage.PROPOSAL: "Close it",
    Stage.CALL: "Send the proposal",
    Stage.TALKING: "Book the call",
}


def next_step(mine: dict[str, Any], today: date) -> str:
    s = stage(mine)
    if s in NEXT_STEP:
        return NEXT_STEP[s]
    if s is Stage.CLOSED:
        return "Closed: lost" if mine.get("status") == "lost" else "Skipped"
    if s is Stage.UNTOUCHED:
        return "Send the first message" if step_day(mine, "researched") else "Read the dossier"
    follow = next_follow_up(mine)
    return f"Follow-up {follow.step[-1]}, {due_text(follow.due, today)}" if follow else "Wait for a reply"


def due_text(due: date, today: date) -> str:
    n = (due - today).days
    if n < 0:
        return f"overdue {-n} day{'s' if n != -1 else ''}"
    if n == 0:
        return "due today"
    if n == 1:
        return "due tomorrow"
    return f"due {due:%b %-d}"


def goal_for(day: date, goals: dict[str, int]) -> int:
    if day.isoformat() in goals:
        return max(0, int(goals[day.isoformat()]))
    return int(goals.get("default", DEFAULT_GOAL)) if is_weekday(day) else 0


@dataclass(frozen=True)
class Streak:
    current: int
    best: int


def streak(hits: Counter[date], goals: dict[str, int], start: date | None, today: date) -> Streak:
    """Days in a row where hits met the goal. Days with no goal (weekends by default) are skipped; a missed day
    resets the run, except today, which is still in progress."""
    if start is None:
        return Streak(0, 0)
    run = best = 0
    day = start
    while day <= today:
        goal = goal_for(day, goals)
        if goal:
            if hits.get(day, 0) >= goal:
                run += 1
                best = max(best, run)
            elif day != today:
                run = 0
        day += timedelta(days=1)
    return Streak(run, best)


@dataclass(frozen=True)
class Level:
    number: int
    name: str
    floor_xp: int
    next_xp: int | None
    next_name: str | None


def level_for(total: int) -> Level:
    index = max(i for i, (threshold, _) in enumerate(LEVELS) if total >= threshold)
    floor, name = LEVELS[index]
    upcoming = LEVELS[index + 1] if index + 1 < len(LEVELS) else None
    return Level(
        number=index + 1,
        name=name,
        floor_xp=floor,
        next_xp=upcoming[0] if upcoming else None,
        next_name=upcoming[1] if upcoming else None,
    )


@dataclass(frozen=True)
class Badge:
    key: str
    name: str
    description: str
    earned: bool


def badges(mines: Iterable[dict[str, Any]], hits: Counter[date], best_streak: int) -> list[Badge]:
    mines = list(mines)
    most_in_a_day = max(hits.values(), default=0)
    total_hits = sum(hits.values())

    def touched_people(m: dict[str, Any]) -> int:
        return sum(1 for kinds in (m.get("touches") or {}).values() if any(_day(v) for v in kinds.values()))

    def channels(m: dict[str, Any]) -> set[str]:
        return {k for kinds in (m.get("touches") or {}).values() for k, v in kinds.items() if _day(v)}

    follow_ups = sum(1 for m in mines for s in ("fu1", "fu2") if step_day(m, s))
    ever = {s: any(step_day(m, s) for m in mines) for s in ("replied", "call", "proposal")}
    clients = any(stage(m) is Stage.WON for m in mines)
    spec = [
        ("first_hit", "First hit", "Reach your first company", total_hits >= 1),
        ("hat_trick", "Hat trick", "Reach 3 companies in one day", most_in_a_day >= 3),
        ("perfect_10", "Perfect 10", "Reach 10 companies in one day", most_in_a_day >= 10),
        (
            "multi_threader",
            "Multi-threader",
            "Reach 3 people at one company",
            any(touched_people(m) >= 3 for m in mines),
        ),
        (
            "triple_channel",
            "Triple channel",
            "Send a request, a DM and an email at one company",
            any(channels(m) >= set(TOUCH_KINDS) for m in mines),
        ),
        ("follow_through", "Follow-through", "Send 10 follow-ups", follow_ups >= 10),
        ("on_fire", "On fire", "Hit your goal 5 days in a row", best_streak >= 5),
        ("fifty", "Fifty", "Reach 50 companies", total_hits >= 50),
        ("first_reply", "First reply", "Get your first reply", ever["replied"]),
        ("first_call", "First call", "Book your first call", ever["call"]),
        ("first_proposal", "First proposal", "Send your first proposal", ever["proposal"]),
        ("first_client", "First client", "Sign your first client", clients),
    ]
    return [Badge(key, name, description, bool(earned)) for key, name, description, earned in spec]


# ----------------------------------------------------------------------------- changes


class FractionalError(ValueError):
    """A change that doesn't make sense (an unknown person or step); the message says why."""


def set_touch(mine: dict[str, Any], person_keys: set[str], person: str, kind: str, on: bool, when: date) -> str:
    """Tick or untick a message. A person the research no longer lists can still be unticked."""
    ticked = person in (mine.get("touches") or {})
    if kind not in TOUCH_KINDS or (person not in person_keys and not (ticked and not on)):
        raise FractionalError("Unknown person or message type.")
    touches = {k: dict(v) for k, v in (mine.get("touches") or {}).items()}
    kinds = touches.setdefault(person, {})
    if on:
        kinds.setdefault(kind, when.isoformat())  # the first tick wins
    else:
        kinds.pop(kind, None)
        if not kinds:
            touches.pop(person)
    mine["touches"] = touches
    return kind


def set_step(mine: dict[str, Any], step: str, on: bool, when: date) -> None:
    if step not in STEPS:
        raise FractionalError("Unknown step.")
    steps = dict(mine.get("steps") or {})
    if on:
        steps.setdefault(step, when.isoformat())
        if step == "won":
            mine["status"] = "won"
    else:
        steps.pop(step, None)
        if step == "won" and mine.get("status") == "won":
            mine["status"] = "open"
    mine["steps"] = steps


def set_status(mine: dict[str, Any], status: str, when: date) -> None:
    """Open, won, lost or skipped. Won and the "won" step always agree: reopening a client un-wins it."""
    if status not in STATUSES:
        raise FractionalError("Unknown status.")
    mine["status"] = status
    steps = dict(mine.get("steps") or {})
    if status == "won":
        steps.setdefault("won", when.isoformat())
    else:
        steps.pop("won", None)
    mine["steps"] = steps


def tomorrow_for(today: date) -> date:
    return next_weekday(today)
