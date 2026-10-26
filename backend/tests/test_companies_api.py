from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Activity, Move, MoveType, PersonStatus, Stage
from tests import factories as f


def test_the_board_lists_companies_with_their_next_move(signed_in: TestClient, db: Session) -> None:
    a = f.company(db, name="Alpha Example", rank=2, domain="alpha.example", open_role="GTM Engineer")
    f.company(db, name="Beta Example", rank=1, stage=Stage.CONTACTED)
    f.move(db, a, type=MoveType.APPLY, due=date(2026, 10, 28), title="Apply later")
    f.move(db, a, type=MoveType.PREP, due=date(2026, 10, 27), title="Prep first")
    f.person(db, a)
    page = signed_in.get("/api/companies").json()
    assert page["total"] == 2
    assert [c["name"] for c in page["items"]] == ["Beta Example", "Alpha Example"]
    alpha = page["items"][1]
    assert (alpha["people_count"], alpha["next_move"]["title"]) == (1, "Prep first")
    assert page["items"][0]["next_move"] is None

    assert signed_in.get("/api/companies", params={"stage": "contacted"}).json()["total"] == 1
    found = signed_in.get("/api/companies", params={"q": "gtm eng"}).json()
    assert [c["id"] for c in found["items"]] == [a.id]
    assert signed_in.get("/api/companies", params={"q": "100%"}).json()["total"] == 0


def test_one_company_puts_the_warmest_people_first(signed_in: TestClient, db: Session) -> None:
    c = f.company(db)
    f.person(db, c, name="Cold Example")
    warm, _ = f.person(db, c, name="Warm Example")
    gone, _ = f.person(db, c, name="Gone Example")
    warm.status = PersonStatus.CONNECTED
    gone.left = True
    gone.status = PersonStatus.REPLIED
    db.flush()
    body = signed_in.get(f"/api/companies/{c.id}").json()
    assert [p["name"] for p in body["people"]] == ["Warm Example", "Cold Example", "Gone Example"]
    assert body["research"] == {}
    assert signed_in.get("/api/companies/nope").status_code == 404


def test_creating_a_company(signed_in: TestClient) -> None:
    r = signed_in.post(
        "/api/companies",
        json={"name": "Gamma Example", "domain": "gamma.example", "research": {"one_liner": "Billing for vets"}},
    )
    assert r.status_code == 201
    assert (r.json()["stage"], r.json()["activity"][0]["text"]) == (
        "not_started",
        "Gamma Example: added to the tracker",
    )
    dup = signed_in.post("/api/companies", json={"name": "Gamma Again", "domain": "GAMMA.example"})
    assert dup.status_code == 409


def test_changing_stage_by_hand(signed_in: TestClient, db: Session) -> None:
    c = f.company(db)
    r = signed_in.patch(f"/api/companies/{c.id}", json={"stage": "parked"})
    assert (r.json()["stage"], r.json()["parked_why"]) == ("parked", "manual")
    r = signed_in.patch(f"/api/companies/{c.id}", json={"stage": "call_booked"})
    assert (r.json()["stage"], r.json()["parked_why"]) == ("call_booked", None)
    signed_in.patch(f"/api/companies/{c.id}", json={"stage": "contacted"})
    signed_in.patch(f"/api/companies/{c.id}", json={"stage": "call_booked"})
    wins = db.scalars(select(Activity.xp).where(Activity.company_id == c.id, Activity.xp > 0)).all()
    assert wins == [25]  # booking the call counts once
    assert signed_in.patch(f"/api/companies/{c.id}", json={"stage": "somewhere"}).status_code == 422


def test_editing_notes_wave_and_research(signed_in: TestClient, db: Session) -> None:
    c = f.company(db, research={"one_liner": "old", "keep": "this"})
    r = signed_in.patch(
        f"/api/companies/{c.id}",
        json={
            "notes": "Met at a meetup",
            "wave": "3",
            "research": {"one_liner": "new", "drop": None},
            "cant_apply": True,
        },
    )
    body = r.json()
    assert body["notes"] == "Met at a meetup"
    assert body["wave"] == "3"
    assert body["research"] == {"one_liner": "new", "keep": "this"}
    assert body["cant_apply"] is True
    assert any(a["text"] == "Acme Example: moved to wave 3" for a in body["activity"])


def test_promoting_off_the_bench(signed_in: TestClient, db: Session) -> None:
    c = f.company(db, stage=Stage.BENCH)
    p, _ = f.person(db, c, name="Still Here")
    gone, _ = f.person(db, c, name="Gone Example")
    gone.left = True
    db.flush()
    r = signed_in.post(f"/api/companies/{c.id}/promote", json={"wave": "4"})
    assert r.status_code == 200
    body = r.json()
    assert (body["stage"], body["wave"]) == ("researching", "4")
    reach = db.scalars(select(Move).where(Move.company_id == c.id, Move.type == MoveType.REACH)).all()
    assert [(m.person_id, m.due) for m in reach] == [(p.id, date(2026, 10, 27))]
    assert db.scalar(select(func.count()).select_from(Move).where(Move.type == MoveType.RESEARCH)) == 1
    again = signed_in.post(f"/api/companies/{c.id}/promote", json={})
    assert again.status_code == 409


def test_promoting_a_company_with_nobody_yet(signed_in: TestClient, db: Session) -> None:
    c = f.company(db, stage=Stage.BENCH)
    signed_in.post(f"/api/companies/{c.id}/promote", json={})
    types = set(db.scalars(select(Move.type).where(Move.company_id == c.id)))
    assert types == {MoveType.RESEARCH, MoveType.EMAIL}
