from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Activity, Move, MoveStatus, MoveType, Person, PersonStatus, Stage
from tests import factories as f
from tests.conftest import TODAY


def test_a_found_person_takes_over_the_find_them_move(signed_in: TestClient, db: Session) -> None:
    c = f.company(db)
    earlier = TODAY - timedelta(days=2)
    finder = f.move(db, c, type=MoveType.EMAIL, due=earlier, title="Email the hiring manager (find them first)")
    r = signed_in.post(
        "/api/people",
        json={
            "company_id": c.id,
            "name": "  Robin   Example ",
            "title": "VP Revenue",
            "email": "Robin@Example.COM",
            "linkedin": "https://www.linkedin.com/in/robin-example",
            "role_in_hire": "hiring manager",
            "sureness": "confirmed",
            "why": "Posted the role",
        },
    )
    assert r.status_code == 201
    person = r.json()
    assert (person["name"], person["email"]) == ("Robin Example", "robin@example.com")
    reach = db.scalars(select(Move).where(Move.person_id == person["id"])).one()
    assert (reach.type, reach.due, reach.sequence["next"]) == (MoveType.REACH, earlier, "email+request")
    db.refresh(finder)
    assert finder.status is MoveStatus.DONE
    assert finder.notes.endswith("[found: Robin Example]")

    second = signed_in.post("/api/people", json={"company_id": c.id, "name": "Sam Example"}).json()
    assert db.scalars(select(Move.due).where(Move.person_id == second["id"])).one() == TODAY


def test_adding_a_person_checks_the_input(signed_in: TestClient, db: Session) -> None:
    c = f.company(db)
    f.person(db, c, name="Pat Example")
    assert signed_in.post("/api/people", json={"company_id": c.id, "name": "pat example"}).status_code == 409
    assert signed_in.post("/api/people", json={"company_id": "nope", "name": "Lee"}).status_code == 404
    bad = signed_in.post("/api/people", json={"company_id": c.id, "name": "Lee", "email": "not an email"})
    assert bad.status_code == 422
    assert signed_in.post("/api/people", json={"company_id": c.id, "name": ""}).status_code == 422


def test_a_reply_ends_the_outreach_and_counts_once(signed_in: TestClient, db: Session) -> None:
    c = f.company(db)
    p, m = f.person(db, c, day0=TODAY)
    assert m is not None
    bump = f.move(db, c, type=MoveType.BUMP, due=TODAY, person=p)

    r = signed_in.post(f"/api/people/{p.id}/reply", json={"text": "Happy to chat Thursday"})
    assert r.json()["status"] == "replied"
    db.refresh(c)
    db.refresh(m)
    db.refresh(bump)
    assert c.stage is Stage.REPLIED
    assert (m.status, m.sequence["next"], m.sequence["replied"]) == (MoveStatus.DONE, "replied", "2026-10-26")
    assert bump.status is MoveStatus.SKIPPED
    signed_in.post(f"/api/people/{p.id}/reply", json={})
    xp = db.scalars(select(Activity.xp).where(Activity.kind == "reply", Activity.person_id == p.id)).all()
    assert sorted(xp) == [0, 10]


def test_marking_replied_by_status_is_a_reply_too(signed_in: TestClient, db: Session) -> None:
    c = f.company(db, stage=Stage.PARKED)
    p, _ = f.person(db, c, day0=TODAY)
    signed_in.patch(f"/api/people/{p.id}", json={"status": "replied"})
    db.refresh(c)
    assert c.stage is Stage.PARKED  # a reply at a parked company doesn't unpark it
    assert db.scalar(select(func.sum(Activity.xp)).where(Activity.person_id == p.id)) == 10


def test_editing_a_person(signed_in: TestClient, db: Session) -> None:
    c = f.company(db)
    p, m = f.person(db, c, day0=TODAY)
    assert m is not None
    r = signed_in.patch(
        f"/api/people/{p.id}",
        json={"title": "CRO", "status": "declined", "email": None, "sureness": None, "ab_variant": "B"},
    )
    body = r.json()
    assert (body["title"], body["status"], body["sureness"], body["ab_variant"]) == ("CRO", "declined", None, "B")
    r = signed_in.patch(f"/api/people/{p.id}", json={"left": True})
    assert r.json()["left"] is True
    db.refresh(m)
    assert (m.status, m.sequence["next"]) == (MoveStatus.DONE, "closed")
    assert "left the company" in m.notes
    assert signed_in.patch(f"/api/people/{p.id}", json={"left": False}).json()["left"] is False
    assert signed_in.patch("/api/people/nope", json={"title": "x"}).status_code == 404


def test_listing_people(signed_in: TestClient, db: Session) -> None:
    c = f.company(db)
    f.person(db, c, name="Ana Example")
    p, _ = f.person(db, c, name="Bo Example")
    p.status = PersonStatus.CONNECTED
    db.flush()
    page = signed_in.get("/api/people", params={"q": "example", "limit": 1}).json()
    assert (page["total"], [x["name"] for x in page["items"]]) == (2, ["Ana Example"])
    connected = signed_in.get("/api/people", params={"status": "connected", "company_id": c.id}).json()
    assert [x["name"] for x in connected["items"]] == ["Bo Example"]
    assert signed_in.get("/api/people", params={"role": "recruiter", "sureness": "confirmed"}).json()["total"] == 0
    assert db.scalar(select(func.count()).select_from(Person)) == 2
