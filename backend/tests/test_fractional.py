"""The Fractional rules (Monday 2026-10-26 is today)."""

from collections import Counter
from datetime import date, timedelta

import pytest

from app.services import fractional as fx

MON = date(2026, 10, 26)


def touched(on: str = "2026-10-26", **extra: object) -> dict[str, object]:
    return {"status": "open", "touches": {"ana": {"connect": on}}, **extra}


def test_stage_follows_the_furthest_step() -> None:
    assert fx.stage({}) is fx.Stage.UNTOUCHED
    assert fx.stage(touched()) is fx.Stage.WAITING
    assert fx.stage(touched(steps={"replied": "2026-10-28"})) is fx.Stage.TALKING
    assert fx.stage(touched(steps={"replied": "x", "call": "2026-10-29"})) is fx.Stage.CALL
    assert fx.stage(touched(status="lost")) is fx.Stage.CLOSED
    assert fx.stage(touched(steps={"won": "2026-11-02"})) is fx.Stage.WON


def test_follow_ups_come_three_then_four_working_days_later() -> None:
    first = fx.next_follow_up(touched())
    assert first == fx.FollowUp("fu1", date(2026, 10, 29))
    second = fx.next_follow_up(touched(steps={"fu1": "2026-10-29"}))
    assert second == fx.FollowUp("fu2", date(2026, 11, 4))
    assert fx.next_follow_up(touched(steps={"fu1": "2026-10-29", "fu2": "2026-11-04"})) is None
    assert fx.next_follow_up(touched(steps={"replied": "2026-10-27"})) is None
    assert fx.next_follow_up({}) is None


def test_next_step_in_words() -> None:
    assert fx.next_step({}, MON) == "Read the dossier"
    assert fx.next_step({"steps": {"researched": "2026-10-26"}}, MON) == "Send the first message"
    assert fx.next_step(touched(), MON) == "Follow-up 1, due Oct 29"
    assert fx.next_step(touched(on="2026-10-20"), MON) == "Follow-up 1, overdue 3 days"  # due Fri 23rd
    assert fx.next_step(touched(steps={"fu1": "2026-10-29", "fu2": "2026-11-04"}), MON) == "Wait for a reply"
    assert fx.next_step(touched(status="skipped"), MON) == "Skipped"
    assert fx.next_step(touched(status="lost"), MON) == "Closed: lost"
    assert fx.next_step(touched(steps={"proposal": "2026-10-30"}), MON) == "Close it"
    assert fx.due_text(MON, MON) == "due today"
    assert fx.due_text(MON + timedelta(days=1), MON) == "due tomorrow"
    assert fx.due_text(MON - timedelta(days=3), MON) == "overdue 3 days"


def test_xp_counts_each_message_and_step() -> None:
    mine = {"touches": {"ana": {"connect": "d", "dm": "2026-10-27"}, "bo": {"email": "2026-10-27"}}}
    assert fx.xp(mine) == 3 + 3  # "d" isn't a date
    assert fx.xp({**mine, "steps": {"replied": "2026-10-28", "won": "2026-11-01"}}) == 6 + 10 + 100


def test_goals_and_streak_skip_weekends_and_forgive_today() -> None:
    goals = {"default": 2, "2026-10-21": 0}
    assert fx.goal_for(date(2026, 10, 24), goals) == 0  # Saturday
    assert fx.goal_for(MON, goals) == 2
    hits = Counter({date(2026, 10, 19): 2, date(2026, 10, 20): 3, date(2026, 10, 22): 2, date(2026, 10, 23): 2})
    # the 21st has no goal, the weekend is skipped, and today isn't over yet
    assert fx.streak(hits, goals, date(2026, 10, 19), MON) == fx.Streak(4, 4)
    hits[date(2026, 10, 22)] = 1
    assert fx.streak(hits, goals, date(2026, 10, 19), MON) == fx.Streak(1, 2)
    assert fx.streak(hits, goals, None, MON) == fx.Streak(0, 0)


def test_levels() -> None:
    assert fx.level_for(0).name == "Rookie"
    assert (fx.level_for(130).number, fx.level_for(130).next_name, fx.level_for(130).next_xp) == (3, "Connector", 220)
    assert fx.level_for(5000).next_xp is None


def test_badges() -> None:
    mines = [
        {"touches": {"a": {"connect": "1"}, "b": {"dm": "1"}, "c": {"email": "1"}}, "steps": {"replied": "2026-10-27"}}
    ]
    earned = {b.key for b in fx.badges(mines, Counter({MON: 3}), best_streak=5) if b.earned}
    assert earned == {"first_hit", "hat_trick", "on_fire", "first_reply"}
    real = [
        {
            "touches": {
                "a": {"connect": "2026-10-26", "dm": "2026-10-26", "email": "2026-10-26"},
                "b": {"dm": "2026-10-26"},
                "c": {"dm": "2026-10-26"},
            }
        }
    ]
    earned = {b.key for b in fx.badges(real, Counter({MON: 1}), 0) if b.earned}
    assert {"multi_threader", "triple_channel"} <= earned


def test_changes() -> None:
    mine: dict[str, object] = {"status": "open"}
    fx.set_touch(mine, {"ana"}, "ana", "connect", True, MON)
    fx.set_touch(mine, {"ana"}, "ana", "connect", True, MON + timedelta(days=1))
    assert mine["touches"] == {"ana": {"connect": "2026-10-26"}}  # the first tick wins
    fx.set_touch(mine, {"ana"}, "ana", "connect", False, MON)
    assert mine["touches"] == {}
    with pytest.raises(fx.FractionalError):
        fx.set_touch(mine, {"ana"}, "bo", "connect", True, MON)
    fx.set_touch(mine, {"ana"}, "ana", "dm", True, MON)
    fx.set_touch(mine, set(), "ana", "dm", False, MON)  # the research dropped Ana: her tick can still come off
    assert mine["touches"] == {}
    with pytest.raises(fx.FractionalError):
        fx.set_touch(mine, set(), "ana", "dm", True, MON)
    fx.set_step(mine, "won", True, MON)
    assert mine["status"] == "won"
    fx.set_step(mine, "won", False, MON)
    assert mine.get("status") == "open"
    fx.set_status(mine, "won", MON)
    assert mine["steps"] == {"won": "2026-10-26"}
    fx.set_status(mine, "open", MON)  # reopening a client un-wins it
    assert mine["steps"] == {}
    with pytest.raises(fx.FractionalError):
        fx.set_step(mine, "dance", True, MON)
    with pytest.raises(fx.FractionalError):
        fx.set_status(mine, "maybe", MON)
    assert fx.tomorrow_for(date(2026, 10, 30)) == date(2026, 11, 2)
