from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Activity, Move, MoveStatus, MoveType, ParkedWhy, PersonStatus, Stage
from tests import factories as f
from tests.conftest import TODAY


def fresh(value: object) -> object:
    """A value read again after a request changed it (keeps mypy from narrowing it across requests)."""
    return value


def test_ticking_steps_moves_the_company_and_the_person(signed_in: TestClient, db: Session) -> None:
    c = f.company(db)
    p, m = f.person(db, c, day0=TODAY)
    assert m is not None

    r = signed_in.post(f"/api/moves/{m.id}/steps", json={"step": "request"})
    assert r.status_code == 200
    assert r.json()["sequence"]["next"] == "email"
    db.refresh(p)
    assert p.status is PersonStatus.REQUESTED
    assert fresh(c.stage) is Stage.NOT_STARTED  # a request alone isn't contact

    r = signed_in.post(f"/api/moves/{m.id}/steps", json={"step": "email"})
    body = r.json()
    assert (body["status"], body["sequence"]["next"], body["due"]) == ("open", "bump", "2026-10-30")
    db.refresh(c)
    db.refresh(p)
    assert fresh(c.stage) is Stage.CONTACTED
    assert p.emailed_at == TODAY

    r = signed_in.post(f"/api/moves/{m.id}/steps", json={"step": "accepted", "value": "2026-10-26"})
    assert r.json()["sequence"]["next"] == "dm"
    db.refresh(p)
    assert fresh(p.status) is PersonStatus.CONNECTED

    r = signed_in.post(f"/api/moves/{m.id}/steps", json={"step": "accepted", "value": None})
    assert r.json()["sequence"]["next"] == "bump"
    lines = db.scalars(select(Activity.text).where(Activity.move_id == m.id)).all()
    assert "Emailed Pat Example" in lines


def test_steps_only_on_a_reach_out_and_never_in_the_future(signed_in: TestClient, db: Session) -> None:
    c = f.company(db)
    apply = f.move(db, c, type=MoveType.APPLY, due=TODAY)
    r = signed_in.post(f"/api/moves/{apply.id}/steps", json={"step": "email"})
    assert r.status_code == 409
    _, m = f.person(db, c, day0=TODAY)
    assert m is not None
    tomorrow = (TODAY + timedelta(days=1)).isoformat()
    r = signed_in.post(f"/api/moves/{m.id}/steps", json={"step": "email", "value": tomorrow})
    assert r.status_code == 409
    assert signed_in.post(f"/api/moves/{m.id}/steps", json={"step": "wave"}).status_code == 422
    assert signed_in.post("/api/moves/nope/steps", json={"step": "email"}).status_code == 404


def test_closing_rescheduling_and_reopening_a_reach_out(signed_in: TestClient, db: Session) -> None:
    c = f.company(db)
    _, m = f.person(db, c, day0=TODAY)
    assert m is not None
    r = signed_in.patch(f"/api/moves/{m.id}", json={"due": "2026-10-29"})
    assert (r.json()["due"], r.json()["sequence"]["day0"]) == ("2026-10-29", "2026-10-29")
    r = signed_in.patch(f"/api/moves/{m.id}", json={"status": "skipped"})
    assert (r.json()["status"], r.json()["sequence"]["next"]) == ("done", "closed")
    assert r.json()["done_at"] is not None
    r = signed_in.patch(f"/api/moves/{m.id}", json={"status": "open"})
    assert (r.json()["status"], r.json()["sequence"]["next"]) == ("open", "email+request")


def test_skipping_the_application_parks_an_untouched_company(signed_in: TestClient, db: Session) -> None:
    c = f.company(db)
    apply = f.move(db, c, type=MoveType.APPLY, due=TODAY)
    signed_in.patch(f"/api/moves/{apply.id}", json={"status": "skipped"})
    db.refresh(c)
    assert (c.stage, c.parked_why) == (Stage.PARKED, ParkedWhy.SKIPPED_APPLY)
    assert "Oct 26" in (c.parked_reason or "")

    signed_in.patch(f"/api/moves/{apply.id}", json={"status": "open"})
    db.refresh(c)
    assert (c.stage, c.parked_why, c.parked_reason) == (Stage.NOT_STARTED, None, None)

    # "US only": skipped, but the company stays
    signed_in.patch(f"/api/moves/{apply.id}", json={"status": "skipped", "skip_reason": "US only"})
    db.refresh(c)
    assert c.stage is Stage.NOT_STARTED


def test_skipping_after_reaching_someone_keeps_the_company(signed_in: TestClient, db: Session) -> None:
    c = f.company(db)
    _, m = f.person(db, c, day0=TODAY)
    assert m is not None
    signed_in.post(f"/api/moves/{m.id}/steps", json={"step": "request"})
    apply = f.move(db, c, type=MoveType.APPLY, due=TODAY)
    signed_in.patch(f"/api/moves/{apply.id}", json={"status": "skipped"})
    db.refresh(c)
    assert c.stage is Stage.NOT_STARTED


def test_finishing_other_moves(signed_in: TestClient, db: Session) -> None:
    c = f.company(db)
    p, _ = f.person(db, c)
    email = f.move(db, c, type=MoveType.EMAIL, due=TODAY, person=p)
    r = signed_in.patch(f"/api/moves/{email.id}", json={"status": "done"})
    assert r.json()["status"] == "done"
    db.refresh(c)
    db.refresh(p)
    assert (c.stage, p.emailed_at) == (Stage.CONTACTED, TODAY)

    connect = f.move(db, c, type=MoveType.CONNECT, due=TODAY, person=p)
    signed_in.patch(f"/api/moves/{connect.id}", json={"status": "done"})
    db.refresh(p)
    assert p.status is PersonStatus.REQUESTED

    call = f.move(db, c, type=MoveType.CALL, due=TODAY)
    signed_in.patch(f"/api/moves/{call.id}", json={"status": "done"})
    db.refresh(c)
    assert c.stage is Stage.CALL_BOOKED

    r = signed_in.patch(f"/api/moves/{call.id}", json={"status": "open", "due": "2026-10-28", "notes": "moved"})
    assert (r.json()["status"], r.json()["due"], r.json()["done_at"], r.json()["notes"]) == (
        "open",
        "2026-10-28",
        None,
        "moved",
    )


def test_adding_and_deleting_a_move(signed_in: TestClient, db: Session) -> None:
    c = f.company(db)
    r = signed_in.post(
        "/api/moves",
        json={"type": "prep", "title": "Prep the case study", "company_id": c.id, "url": "https://example.com/a"},
    )
    assert r.status_code == 201
    body = r.json()
    assert (body["due"], body["company"]["name"], body["sequence"]) == ("2026-10-26", "Acme Example", None)
    assert signed_in.post("/api/moves", json={"type": "reach", "title": "x"}).status_code == 409
    assert signed_in.post("/api/moves", json={"title": "x", "company_id": "nope"}).status_code == 404
    assert signed_in.post("/api/moves", json={"title": "x", "url": "javascript:alert(1)"}).status_code == 422
    r = signed_in.patch(f"/api/moves/{body['id']}", json={"url": None})
    assert r.json()["url"] is None
    assert signed_in.delete(f"/api/moves/{body['id']}").status_code == 204
    assert db.get(Move, body["id"]) is None
    assert signed_in.delete(f"/api/moves/{body['id']}").status_code == 404


def test_pull_forward_skips_paused_companies_and_follow_ups(signed_in: TestClient, db: Session) -> None:
    live = f.company(db)
    parked = f.company(db, name="Parked Example", stage=Stage.PARKED)
    later = TODAY + timedelta(days=3)
    f.move(db, parked, type=MoveType.PREP, due=TODAY + timedelta(days=1))
    _, waiting = f.person(db, live, name="Sent Already", day0=TODAY)
    assert waiting is not None
    waiting.sequence = {**waiting.sequence, "steps": {"email": "2026-10-26", "request": "2026-10-26"}}
    _, fresh = f.person(db, live, name="Not Yet", day0=later)
    prep = f.move(db, live, type=MoveType.PREP, due=later)
    other = f.move(db, None, type=MoveType.CUSTOM, due=later + timedelta(days=1))
    db.flush()

    r = signed_in.post("/api/moves/pull", json={"n": 2})
    pulled = {m["id"] for m in r.json()["pulled"]}
    assert fresh is not None
    assert pulled == {fresh.id, prep.id}
    db.refresh(fresh)
    assert (fresh.due, fresh.sequence["day0"]) == (TODAY, TODAY.isoformat())
    assert other.status is MoveStatus.OPEN
    assert signed_in.post("/api/moves/pull", json={"n": 0}).status_code == 422


def test_moves_need_a_session(client: TestClient, db: Session) -> None:
    m = f.move(db, None, type=MoveType.CUSTOM, due=date(2026, 10, 26))
    assert client.patch(f"/api/moves/{m.id}", json={"status": "done"}).status_code == 401
