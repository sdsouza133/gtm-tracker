from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session, sessionmaker

from app.api.radar import Runtime
from app.config import get_settings
from app.models import Company, Move, MoveType, RadarItem, Setting, Stage
from app.radar import run as radar
from tests import factories as f
from tests.conftest import TODAY
from tests.radar_fakes import FakeApify, FakeWeb, ashby, ashby_job

UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


@pytest.fixture
def web() -> FakeWeb:
    return FakeWeb()


@pytest.fixture
def radar_client(signed_in: TestClient, connection: Connection, web: FakeWeb) -> TestClient:
    """Radar work runs inline, on the test's transaction, with a fake network."""
    factory = sessionmaker(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    signed_in.app.state.radar_runtime = Runtime(  # type: ignore[attr-defined]
        settings=get_settings(),
        tools=lambda: radar.Tools(web=web, apify=FakeApify()),
        spawn=lambda work: work(),
        factory=factory,
    )
    return signed_in


def item(db: Session, item_id: str = "li-1", **data: Any) -> RadarItem:
    row = RadarItem(
        id=item_id,
        company=data.pop("company", "Delta Example"),
        title=data.pop("title", "GTM Engineer"),
        url=data.pop("url", "https://www.linkedin.com/jobs/view/1"),
        posted=date(2026, 10, 25),
        fit=3,
        data={"location": "Remote", "salary": "$150K", "flags": ["remote"], "website": "https://delta.example", **data},
    )
    db.add(row)
    db.flush()
    return row


def test_state_and_config(radar_client: TestClient, db: Session) -> None:
    item(db)
    item(db, "li-2", title="GTM Ops")
    db.add(
        Setting(
            key="radar_posts",
            value=[
                {
                    "id": "p1",
                    "url": "u",
                    "posted": "",
                    "author": "Pat",
                    "author_url": "",
                    "headline": "",
                    "recruiter": False,
                    "text": "We're hiring",
                }
            ],
        )
    )
    db.flush()
    body = radar_client.get("/api/radar").json()
    assert [i["id"] for i in body["items"]] == ["li-1", "li-2"]
    assert (body["apify"], body["config"]["hour"], body["posts"][0]["author"]) == (False, 7, "Pat")
    r = radar_client.patch("/api/radar/config", json={"hour": 9, "keywords": ["GTM Engineer"]})
    assert (r.json()["hour"], r.json()["keywords"], r.json()["min_usd"]) == (9, ["GTM Engineer"], 100000)
    r = radar_client.patch("/api/radar/config", json={"min_fit": 3})
    assert (r.json()["hour"], r.json()["min_fit"]) == (9, 3)  # other keys survive a partial change
    assert radar_client.patch("/api/radar/config", json={"hour": 25}).status_code == 422


def test_adding_a_role_at_a_new_company(radar_client: TestClient, db: Session, web: FakeWeb) -> None:
    item(db)
    web.json_by_url.update(ashby("delta", ashby_job("GTM Engineer", UUID, descriptionPlain="We are delta.example")))
    r = radar_client.post("/api/radar/items/li-1/add")
    assert r.status_code == 200
    company = db.get(Company, r.json()["company_id"])
    assert company is not None
    assert (company.name, company.domain, company.wave, company.stage) == (
        "Delta Example",
        "delta.example",
        "radar",
        Stage.NOT_STARTED,
    )
    moves = {m.type: m for m in db.scalars(select(Move).where(Move.company_id == company.id))}
    assert set(moves) == {MoveType.APPLY, MoveType.EMAIL}
    assert moves[MoveType.APPLY].due == TODAY
    # the board search ran afterwards and found the direct posting
    db.refresh(moves[MoveType.APPLY])
    assert moves[MoveType.APPLY].url == f"https://jobs.ashbyhq.com/acme/{UUID}"
    assert moves[MoveType.APPLY].notes.startswith("Direct link on their Ashby board.")
    assert radar_client.post("/api/radar/items/li-1/add").status_code == 409


def test_adding_a_role_at_a_bench_company_brings_it_in(radar_client: TestClient, db: Session) -> None:
    c = f.company(
        db, name="Delta Example", stage=Stage.BENCH, research={"jobs": {"board": {"ats": "ashby", "slug": "delta"}}}
    )
    item(db, company_id=None)
    radar_client.post("/api/radar/items/li-1/add", json={})
    db.refresh(c)
    assert c.stage is Stage.NOT_STARTED
    assert c.research["jobs"]["postings"][0]["title"] == "GTM Engineer"
    us_only = item(db, "li-9", flags=["us_only"])
    radar_client.post(f"/api/radar/items/{us_only.id}/add")
    notes = db.scalars(select(Move.notes).where(Move.company_id == c.id, Move.type == MoveType.APPLY)).all()
    assert any("US work authorization" in n for n in notes)


def test_dismiss_and_run(radar_client: TestClient, db: Session) -> None:
    item(db)
    r = radar_client.post("/api/radar/items/li-1/dismiss")
    assert r.json()["state"] == "dismissed"
    assert radar_client.get("/api/radar").json()["items"] == []
    assert radar_client.post("/api/radar/items/nope/dismiss").status_code == 404
    assert radar_client.post("/api/radar/run").status_code == 202
    status = db.get(Setting, "radar_status")
    assert status is not None
    assert status.value["trigger"] == "manual"
    status.value = {**status.value, "running": True}
    db.flush()
    assert radar_client.post("/api/radar/run").status_code == 409
