from collections import Counter
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Activity, MoveStatus, MoveType, PersonStatus, Setting, Stage, Sureness
from app.services.stats import level_for, streaks
from tests import factories as f
from tests.conftest import NOON, TODAY


def test_today_groups_the_work_and_hides_paused_companies(signed_in: TestClient, db: Session) -> None:
    newer = f.company(db, name="Newer Example", posted=TODAY - timedelta(days=1))
    older = f.company(db, name="Older Example", posted=TODAY - timedelta(days=9))
    parked = f.company(db, name="Parked Example", stage=Stage.PARKED)
    f.move(db, older, type=MoveType.APPLY, due=TODAY, title="Apply older")
    f.move(db, newer, type=MoveType.APPLY, due=TODAY, title="Apply newer")
    f.move(db, newer, type=MoveType.INTERVIEW, due=TODAY - timedelta(days=1), title="Interview")
    f.move(db, parked, type=MoveType.APPLY, due=TODAY, title="Apply parked")
    f.move(db, None, type=MoveType.PREP, due=TODAY, title="Write the case study")
    f.move(db, newer, type=MoveType.PREP, due=TODAY + timedelta(days=1), title="Tomorrow")
    f.person(db, newer, name="Guess Example", sure=Sureness.GUESS, day0=TODAY)
    f.person(db, newer, name="Sure Example", sure=Sureness.CONFIRMED, day0=TODAY)
    _, followup = f.person(db, older, name="Accepted Example", day0=TODAY - timedelta(days=3))
    assert followup is not None
    followup.sequence = {**followup.sequence, "steps": {"email": "2026-10-23", "request": "2026-10-23"}}
    followup.due = TODAY
    followup.sequence = {**followup.sequence, "next": "bump"}
    db.flush()

    body = signed_in.get("/api/today").json()
    assert body["today"] == "2026-10-26"
    assert body["overdue"] == 1
    groups = {g["key"]: [m["title"] for m in g["moves"]] for g in body["groups"]}
    assert list(groups) == ["calls", "apply", "reach_out", "follow_up", "prep"]
    assert groups["apply"] == ["Apply newer", "Apply older"]
    assert groups["reach_out"] == ["Reach out to Sure Example", "Reach out to Guess Example"]
    assert groups["follow_up"] == ["Reach out to Accepted Example"]
    assert groups["prep"] == ["Write the case study"]
    card = body["groups"][2]["moves"][0]
    assert (card["company"]["name"], card["person"]["sureness"]) == ("Newer Example", "confirmed")


def test_done_today_and_waiting(signed_in: TestClient, db: Session) -> None:
    c = f.company(db)
    _, m = f.person(db, c, day0=TODAY)
    assert m is not None
    signed_in.post(f"/api/moves/{m.id}/steps", json={"step": "email"})
    signed_in.post(f"/api/moves/{m.id}/steps", json={"step": "request"})
    prep = f.move(db, c, type=MoveType.PREP, due=TODAY)
    signed_in.patch(f"/api/moves/{prep.id}", json={"status": "done"})
    body = signed_in.get("/api/today").json()
    assert {x["id"] for x in body["done_today"]} == {m.id, prep.id}
    assert [x["id"] for x in body["waiting"]] == [m.id]
    assert body["waiting_total"] == 1
    assert body["groups"] == []


def test_today_keeps_to_the_last_week_and_a_days_worth_of_companies(signed_in: TestClient, db: Session) -> None:
    companies = [f.company(db, name=f"Co {i}") for i in range(7)]
    for c in companies:
        f.move(db, c, type=MoveType.PREP, due=TODAY, title=f"Prep {c.name}")
    f.move(db, companies[0], type=MoveType.APPLY, due=TODAY - timedelta(days=2), title="Apply first")
    f.move(db, companies[1], type=MoveType.PREP, due=TODAY - timedelta(days=8), title="Stale")
    _, unstarted = f.person(db, companies[2], name="Old Example", day0=TODAY - timedelta(days=20))
    assert unstarted is not None
    f.move(db, None, type=MoveType.PREP, due=TODAY, title="Loose task")
    done = f.move(db, companies[6], type=MoveType.PREP, due=TODAY, title="Already done")
    signed_in.patch(f"/api/moves/{done.id}", json={"status": "done"})

    body = signed_in.get("/api/today").json()
    titles = [m["title"] for g in body["groups"] for m in g["moves"]]
    shown = {m["company"]["name"] for g in body["groups"] for m in g["moves"] if m["company"]}
    assert titles[0] == "Apply first"
    assert "Stale" not in titles
    assert "Reach out to Old Example" in titles  # an unstarted reach-out never goes stale
    assert "Loose task" in titles
    assert len(shown) == 5  # Co 6, worked on today, counts toward the five
    assert "Co 6" in shown
    assert body["more"] == 2


def test_a_loom_request_shows_until_its_sent(signed_in: TestClient, db: Session) -> None:
    c = f.company(db, name="Loom Example")
    p, _ = f.person(db, c, name="Asker Example", day0=TODAY)
    signed_in.patch(f"/api/people/{p.id}", json={"loom": "asked"})
    body = signed_in.get("/api/today").json()
    assert [(x["person"]["name"], x["company"]["name"]) for x in body["looms"]] == [("Asker Example", "Loom Example")]
    db.refresh(p)
    assert (p.status, p.details["loom_asked"]) == (PersonStatus.REPLIED, "2026-10-26")
    signed_in.patch(f"/api/people/{p.id}", json={"loom": "sent"})
    assert signed_in.get("/api/today").json()["looms"] == []


def test_clearing_the_backlog_skips_only_moves_over_a_week_old(signed_in: TestClient, db: Session) -> None:
    c = f.company(db)
    stale = [f.move(db, c, type=MoveType.APPLY, due=TODAY - timedelta(days=d)) for d in (8, 30)]
    recent = f.move(db, c, type=MoveType.APPLY, due=TODAY - timedelta(days=7))
    finished = f.move(db, c, type=MoveType.APPLY, due=TODAY - timedelta(days=30), status=MoveStatus.DONE)

    assert signed_in.post("/api/moves/clear-backlog").json() == {"cleared": 2}
    for m in (*stale, recent, finished):
        db.refresh(m)
    assert [m.status for m in stale] == [MoveStatus.SKIPPED, MoveStatus.SKIPPED]
    assert stale[0].skip_reason == "Old backlog, cleared"
    assert (recent.status, finished.status) == (MoveStatus.OPEN, MoveStatus.DONE)
    assert c.stage is not Stage.PARKED  # clearing old moves doesn't pass on the company
    assert db.query(Activity).filter(Activity.text.like("Cleared 2 old moves%")).count() == 1
    assert signed_in.post("/api/moves/clear-backlog").json() == {"cleared": 0}


def test_stats_count_moves_wins_and_day_blocks(signed_in: TestClient, db: Session) -> None:
    c = f.company(db)
    _, m = f.person(db, c, day0=TODAY)
    assert m is not None
    for step in ("email", "request"):
        signed_in.post(f"/api/moves/{m.id}/steps", json={"step": step})
    build = f.move(db, c, type=MoveType.BUILD, due=TODAY)
    signed_in.patch(f"/api/moves/{build.id}", json={"status": "done"})
    yesterday = f.move(db, c, type=MoveType.APPLY, due=TODAY, status=MoveStatus.DONE, done_at=NOON - timedelta(days=1))
    db.add(Activity(kind="reply", text="x replied", xp=10))
    db.add(Setting(key="days", value={"2026-10-26": {"outreach": True, "content": False}}))
    db.add(Setting(key="deadline", value="2026-12-31"))
    db.flush()
    s = signed_in.get("/api/stats").json()
    # email 3 + request 1 + build 8 + apply 3 + reply 10 + one day block 5
    assert s["xp"] == 30
    assert (s["level"], s["level_title"], s["next_level_xp"]) == (1, "Warming up", 40)
    assert (s["today_moves"], s["streak"], s["streak_min"]) == (3, 1, 3)
    assert s["recent"][-1] == {"day": "2026-10-26", "moves": 3}
    assert s["recent"][-2] == {"day": "2026-10-25", "moves": 1}
    assert s["funnel"] == {"contacted": 1, "replied": 0, "call_booked": 0, "offer": 0}
    assert (s["in_play"], s["days_left"]) == (1, 66)
    assert yesterday.id


def test_levels_and_streaks() -> None:
    assert level_for(0).number == 1
    assert (level_for(40).number, level_for(40).title, level_for(40).floor_xp) == (2, "Sending", 40)
    assert level_for(100_000).title == "Closing"
    d = date(2026, 10, 26)
    days = Counter({d - timedelta(days=i): 3 for i in range(1, 4)} | {d - timedelta(days=10 + i): 5 for i in range(5)})
    assert streaks(days, d) == (3, 5)  # today in progress: the run from yesterday still counts
    days[d] = 4
    assert streaks(days, d) == (4, 5)
    assert streaks(Counter({d - timedelta(days=2): 9}), d) == (0, 1)


def test_the_plan_shows_open_moves_by_day(signed_in: TestClient, db: Session) -> None:
    c = f.company(db)
    f.move(db, c, type=MoveType.PREP, due=TODAY + timedelta(days=2), title="Later")
    f.move(db, c, type=MoveType.PREP, due=TODAY, title="Now")
    f.move(db, c, type=MoveType.PREP, due=TODAY + timedelta(days=40), title="Far")
    days = signed_in.get("/api/plan").json()
    assert [(d["day"], [m["title"] for m in d["moves"]]) for d in days] == [
        ("2026-10-26", ["Now"]),
        ("2026-10-28", ["Later"]),
    ]
    assert len(signed_in.get("/api/plan", params={"to": "2026-12-20"}).json()) == 3
    assert signed_in.get("/api/plan", params={"to": "2027-06-01"}).status_code == 422
    assert signed_in.get("/api/plan", params={"from": "2026-10-30", "to": "2026-10-29"}).status_code == 422


def test_history_pages_back_and_takes_notes(signed_in: TestClient, db: Session) -> None:
    c = f.company(db)
    for i in range(3):
        signed_in.post("/api/activity", json={"text": f"note {i}", "company_id": c.id})
    first = signed_in.get("/api/activity", params={"company_id": c.id, "limit": 2}).json()
    assert [a["text"] for a in first["items"]] == ["note 2", "note 1"]
    assert first["total"] == 3  # all the lines that match, not just this page
    rest = signed_in.get("/api/activity", params={"before": first["items"][-1]["id"], "company_id": c.id}).json()
    assert ([a["text"] for a in rest["items"]], rest["total"]) == (["note 0"], 1)
    assert signed_in.post("/api/activity", json={"text": ""}).status_code == 422
    assert signed_in.post("/api/activity", json={"text": "x", "company_id": "nope"}).status_code == 404
    assert signed_in.post("/api/activity", json={"text": "x", "person_id": "nope"}).status_code == 404


def test_settings_only_take_known_keys(signed_in: TestClient) -> None:
    assert signed_in.get("/api/settings").json()["candidate"] is None
    r = signed_in.patch(
        "/api/settings",
        json={"candidate": "Demo Candidate", "days": {"2026-10-26": {"outreach": True}}, "deadline": "2026-12-31"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["candidate"] == "Demo Candidate"
    assert body["days"]["2026-10-26"] == {"outreach": True, "content": False, "course": False}
    assert signed_in.patch("/api/settings", json={"candidate": "Again"}).json()["deadline"] == "2026-12-31"
    assert signed_in.patch("/api/settings", json={"migrations_done": []}).status_code == 422
    # day marks merge day by day: another day keeps its marks, and a mark can be turned off
    signed_in.patch("/api/settings", json={"days": {"2026-10-27": {"content": True}}})
    days = signed_in.patch("/api/settings", json={"days": {"2026-10-26": {"outreach": False}}}).json()["days"]
    assert days["2026-10-27"]["content"] is True
    assert days["2026-10-26"]["outreach"] is False
    assert signed_in.patch("/api/settings", json={"loom_url": "ftp://x"}).status_code == 422


def test_everything_needs_a_session(client: TestClient) -> None:
    for path in ("/api/today", "/api/stats", "/api/plan", "/api/activity", "/api/settings", "/api/companies"):
        assert client.get(path).status_code == 401, path
