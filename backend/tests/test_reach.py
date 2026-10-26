"""The reach-out rules, step by step (day 0 is Monday 2026-10-26)."""

from datetime import date

import pytest

from app.services import reach
from app.services.reach import Step, evaluate

DAY0 = date(2026, 10, 26)


def seq(**steps: str) -> dict[str, object]:
    return {"day0": DAY0.isoformat(), "steps": steps}


@pytest.mark.parametrize(
    ("steps", "open_", "next_", "due"),
    [
        ({}, True, "email+request", DAY0),
        ({"email": "2026-10-26"}, True, "request", DAY0),
        ({"email": "2026-10-26", "request": "2026-10-26"}, True, "bump", date(2026, 10, 30)),
        ({"email": "2026-10-26", "request": "2026-10-28"}, True, "bump", date(2026, 11, 3)),
        ({"email": "2026-10-26", "request": "2026-10-26", "accepted": "2026-10-28"}, True, "dm", date(2026, 10, 28)),
        (
            {"email": "2026-10-26", "request": "2026-10-26", "accepted": "2026-10-28", "dm": "2026-10-28"},
            False,
            "waiting",
            None,
        ),
        ({"email": "2026-10-26", "request": "2026-10-26", "bump": "2026-10-30"}, False, "waiting", None),
        ({"email": "na", "request": "2026-10-26"}, False, "waiting", None),
        ({"email": "na", "request": "2026-10-26", "accepted": "2026-10-29"}, True, "dm", date(2026, 10, 29)),
        ({"request": "na", "email": "2026-10-26", "accepted": "2026-10-29"}, True, "bump", date(2026, 10, 30)),
    ],
)
def test_what_is_due(steps: dict[str, str], open_: bool, next_: str, due: date | None) -> None:
    out = evaluate(seq(**steps), fallback_due=DAY0)
    assert (out.open, out.next, out.due) == (open_, next_, due)


def test_a_reply_or_closing_ends_it() -> None:
    assert evaluate({**seq(), "replied": "2026-10-27"}, DAY0).next == "replied"
    assert evaluate(reach.close(seq(), DAY0), DAY0).next == "closed"
    assert evaluate(reach.reopen(reach.close(seq(), DAY0)), DAY0).open


def test_snooze_only_ever_pushes_later() -> None:
    sent = seq(email="2026-10-26", request="2026-10-26")
    assert evaluate({**sent, "snooze": "2026-11-05"}, DAY0).due == date(2026, 11, 5)
    assert evaluate({**sent, "snooze": "2026-10-27"}, DAY0).due == date(2026, 10, 30)


def test_rescheduling_moves_day0_before_the_first_touches_and_snoozes_after() -> None:
    moved = reach.reschedule(seq(email="2026-10-26"), date(2026, 10, 29))
    assert moved["day0"] == "2026-10-29"
    assert evaluate(moved, DAY0).due == date(2026, 10, 29)
    held = reach.reschedule(seq(email="2026-10-26", request="2026-10-26"), date(2026, 11, 6))
    assert held["snooze"] == "2026-11-06"
    assert evaluate(held, DAY0).due == date(2026, 11, 6)


def test_a_tick_revives_a_closed_row_and_clears_the_snooze() -> None:
    closed = {**reach.close(seq(), DAY0), "snooze": "2026-11-01"}
    ticked = reach.tick(closed, Step.EMAIL, DAY0)
    assert "closed" not in ticked
    assert "snooze" not in ticked
    assert evaluate(ticked, DAY0).next == "request"
    assert reach.tick(ticked, Step.EMAIL, None)["steps"] == {}


def test_step_days_ignore_na() -> None:
    assert reach.step_days(seq(email="na", request="2026-10-26")) == {Step.REQUEST: DAY0}
