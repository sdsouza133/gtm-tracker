"""The reach-out sequence: one row per person, five steps.

    email      the Day 0 email                        } the first touches, both due on Day 0
    request    the LinkedIn connection request        }
    accepted   they accepted the request              -> the LinkedIn message comes due that day
    dm         the LinkedIn message
    bump       one email bump, 4 working days after the later first touch, if they haven't accepted

A step holds the day it was done, or "na" (no email found, not on LinkedIn), or nothing yet. The row is on Today only
when something is due; it closes once the follow-up is sent, and a reply or closing it by hand ends it.

The state lives in `Move.sequence` as JSON: {day0, steps, next, snooze, closed, replied}, dates as ISO strings. These
functions are pure: they take that dict and return a new one with `status`, `next` and `due` worked out.
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any

from app.clock import add_business_days

FOLLOW_UP_WORKING_DAYS = 4
NA = "na"


class Step(StrEnum):
    EMAIL = "email"
    REQUEST = "request"
    ACCEPTED = "accepted"
    DM = "dm"
    BUMP = "bump"


FIRST_TOUCHES = (Step.EMAIL, Step.REQUEST)


@dataclass(frozen=True)
class Outcome:
    open: bool
    next: str  # what's due: "email+request", "request", "dm", "bump"; or "waiting", "replied", "closed"
    due: date | None


def _day(value: Any) -> date | None:
    if isinstance(value, str) and value and value != NA:
        return date.fromisoformat(value)
    return None


def done(steps: dict[str, str], step: Step) -> bool:
    """Done on a real day (not marked n/a)."""
    return _day(steps.get(step)) is not None


def handled(steps: dict[str, str], step: Step) -> bool:
    """Done, or marked n/a."""
    return bool(steps.get(step))


def first_touches_pending(seq: dict[str, Any]) -> bool:
    steps = seq.get("steps") or {}
    return not all(handled(steps, s) for s in FIRST_TOUCHES)


def evaluate(seq: dict[str, Any], fallback_due: date) -> Outcome:
    """What's due on this row, from its ticks."""
    if seq.get("replied"):
        return Outcome(open=False, next="replied", due=None)
    if seq.get("closed"):
        return Outcome(open=False, next="closed", due=None)
    steps: dict[str, str] = seq.get("steps") or {}
    day0 = _day(seq.get("day0")) or fallback_due

    pending = [s.value for s in FIRST_TOUCHES if not handled(steps, s)]
    dates: list[date] = [day0] if pending else []
    accepted = _day(steps.get(Step.ACCEPTED))
    if accepted and not handled(steps, Step.DM) and steps.get(Step.REQUEST) != NA:
        pending.append(Step.DM.value)
        dates.append(accepted)

    outcome: Outcome
    if pending:
        outcome = Outcome(open=True, next="+".join(pending), due=min(dates))
    elif done(steps, Step.EMAIL) and not handled(steps, Step.BUMP) and not done(steps, Step.DM):
        touched = [d for d in (_day(steps.get(s)) for s in FIRST_TOUCHES) if d]
        outcome = Outcome(open=True, next="bump", due=add_business_days(max(touched), FOLLOW_UP_WORKING_DAYS))
    else:
        return Outcome(open=False, next="waiting", due=None)

    snooze = _day(seq.get("snooze"))
    if snooze and outcome.due and snooze > outcome.due:
        return Outcome(open=True, next=outcome.next, due=snooze)
    return outcome


def tick(seq: dict[str, Any], step: Step, value: date | str | None) -> dict[str, Any]:
    """Mark one step done on a day, n/a, or not done (None). Any tick brings a closed row back if something is due,
    and clears a snooze."""
    steps = dict(seq.get("steps") or {})
    if value is None:
        steps.pop(step, None)
    else:
        steps[step] = value.isoformat() if isinstance(value, date) else value
    out = {k: v for k, v in seq.items() if k not in ("closed", "snooze")}
    out["steps"] = steps
    return out


def reschedule(seq: dict[str, Any], to: date) -> dict[str, Any]:
    """Before the first touches, moving it moves Day 0. After, it holds the follow-up until then."""
    out = dict(seq)
    if first_touches_pending(seq):
        out["day0"] = to.isoformat()
        out.pop("snooze", None)
    else:
        out["snooze"] = to.isoformat()
    return out


def close(seq: dict[str, Any], today: date) -> dict[str, Any]:
    return {**seq, "closed": today.isoformat()}


def reopen(seq: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in seq.items() if k not in ("closed", "replied")}


def mark_replied(seq: dict[str, Any], today: date) -> dict[str, Any]:
    return {**seq, "replied": seq.get("replied") or today.isoformat()}


def step_days(seq: dict[str, Any]) -> dict[Step, date]:
    """The steps done on a real day."""
    steps = seq.get("steps") or {}
    return {s: d for s in Step if (d := _day(steps.get(s)))}


def new_sequence(day0: date) -> dict[str, Any]:
    return {"day0": day0.isoformat(), "steps": {}}
