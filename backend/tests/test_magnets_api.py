from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Connection, update
from sqlalchemy.orm import Session, sessionmaker

from app.api import magnets
from app.api.magnets import Runtime
from app.config import Settings, get_settings
from app.magnet.build import Tools
from app.magnet.champions import TREG_CAP_USD
from app.magnet.linkedin import LinkedIn
from app.main import log_path
from app.models import Activity, Company, Magnet, Setting
from tests import champion_fakes
from tests import factories as f
from tests.magnet_fakes import ORGS, FakeApollo, FakeBrain, FakeHarvest, runner, site

KEYS = {"anthropic_api_key": "a-key", "treg_token": "a-treg-token", "apollo_api_key": "an-apollo-key"}


def settings_with(changes: dict[str, Any]) -> Settings:
    secret = {k: SecretStr(v) for k, v in KEYS.items()}
    return get_settings().model_copy(update={**secret, **changes})


@pytest.fixture
def run() -> FakeHarvest:
    return runner()


@pytest.fixture
def started() -> list[Callable[[], None]]:
    return []


@pytest.fixture
def magnet_client(signed_in: TestClient, connection: Connection, run: FakeHarvest) -> TestClient:
    """Builds run inline, on the test's transaction, against the made-up market in magnet_fakes."""
    factory = sessionmaker(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    apollo = FakeApollo(ORGS, emails={"https://www.linkedin.com/in/ana-example": "ana@buyer.example"})
    signed_in.app.state.magnet_runtime = Runtime(  # type: ignore[attr-defined]
        tools=lambda: Tools(
            read_site=site,
            brain=FakeBrain("rivalco.example", "otherco.example"),
            linkedin=LinkedIn(run),
            apollo=apollo,
        ),
        spawn=lambda work: work(),
        factory=factory,
    )
    signed_in.app.dependency_overrides[get_settings] = lambda: settings_with({})  # type: ignore[attr-defined]
    return signed_in


def a_company(db: Session, **kw: Any) -> Company:
    return f.company(db, name="Prospect", website="https://prospect.example", **kw)


def test_a_teaser_builds_in_the_background_and_shares_by_a_private_link(magnet_client: TestClient, db: Session) -> None:
    c = a_company(db)
    r = magnet_client.post(f"/api/companies/{c.id}/magnets", json={"mode": "teaser"})
    assert r.status_code == 202
    assert r.json()["status"] == "running"

    (m,) = magnet_client.get(f"/api/companies/{c.id}/magnets").json()
    assert m["status"] == "ready"
    assert m["mode"] == "teaser"
    assert m["website"] == "https://prospect.example"
    assert m["summary"]["leads"] == 3
    assert m["summary"]["hot"] == 1
    assert m["link"].startswith(f"/m/{m['id']}/")
    assert db.query(Activity).filter(Activity.kind == "magnet").count() == 1

    token = m["link"].rsplit("/", 1)[-1]
    long_ago = datetime(2026, 1, 1, tzinfo=UTC)
    db.execute(update(Magnet).where(Magnet.id == m["id"]).values(updated_at=long_ago))
    magnet_client.cookies.clear()  # the prospect isn't signed in
    report = magnet_client.get(f"/api/public/magnets/{m['id']}/{token}")
    assert report.status_code == 200
    assert report.headers["X-Robots-Tag"] == "noindex, nofollow"
    assert report.headers["Referrer-Policy"] == "no-referrer"
    body = report.json()
    assert body["company"] == "Prospect"
    assert [c["name"] for c in body["competitors"]] == ["RivalCo"]
    assert [lead["name"] for lead in body["leads"]] == ["Ana Example", "Gus Example", "Ben Example"]
    assert body["leads"][0]["email"] is None
    assert "token" not in report.text
    assert magnet_client.get(f"/api/public/magnets/{m['id']}/wrong-token").status_code == 404
    db.expire_all()
    seen = db.get(Magnet, m["id"])
    assert seen is not None
    assert seen.data["views"] == 1
    assert "last_viewed" not in seen.data  # a view changes the count and nothing else
    assert seen.updated_at == long_ago  # so it can't make a stopped build look alive


def test_one_can_be_built_for_any_website_without_a_company(magnet_client: TestClient, db: Session) -> None:
    linked = a_company(db)
    magnet_client.post(f"/api/companies/{linked.id}/magnets", json={"mode": "teaser"})
    # the test runs in one transaction, where now() never moves: date the first one earlier so "newest first" can show
    db.execute(update(Magnet).where(Magnet.company_id == linked.id).values(created_at=datetime(2026, 1, 1, tzinfo=UTC)))
    r = magnet_client.post(
        "/api/magnets",
        json={"mode": "teaser", "website": "https://www.prospect.example/about", "competitors": ["rivalco.example"]},
    )
    assert r.status_code == 202
    m = r.json()
    assert (m["company_id"], m["title"], m["website"]) == (
        None,
        "prospect.example: teaser",
        "https://www.prospect.example/about",
    )

    every = magnet_client.get("/api/magnets").json()  # newest first, with or without a company
    assert [(x["company_id"], x["status"]) for x in every] == [(None, "ready"), (linked.id, "ready")]
    assert every[0]["summary"]["leads"] == 3
    assert every[0]["link"].startswith(f"/m/{m['id']}/")
    assert [x["id"] for x in magnet_client.get(f"/api/companies/{linked.id}/magnets").json()] == [every[1]["id"]]

    named = magnet_client.post("/api/magnets", json={"website": "prospect.example", "name": "Prospect Inc"}).json()
    assert named["title"] == "Prospect Inc: teaser"
    link = magnet_client.get(f"/api/magnets/{named['id']}").json()["link"]
    assert magnet_client.get(f"/api/public{link.replace('/m/', '/magnets/', 1)}").json()["company"] == "Prospect Inc"


@pytest.mark.parametrize("website", ["not a site", "localhost", "  "])
def test_a_build_for_any_website_needs_a_website(magnet_client: TestClient, db: Session, website: str) -> None:
    r = magnet_client.post("/api/magnets", json={"website": website})
    assert r.status_code == 422
    assert db.query(Magnet).count() == 0


def test_one_build_for_a_website_outside_the_tracker_at_a_time(magnet_client: TestClient, db: Session) -> None:
    db.add(Magnet(company_id=None, kind="engagement", status="running", title="x: teaser", data={}))
    db.flush()
    r = magnet_client.post("/api/magnets", json={"website": "prospect.example"})
    assert r.status_code == 409
    assert r.json()["detail"] == "A lead magnet is already building for a website outside the tracker."
    c = a_company(db)  # a company's own build doesn't wait on it
    assert magnet_client.post(f"/api/companies/{c.id}/magnets", json={"mode": "teaser"}).status_code == 202


def test_the_full_build_carries_emails(magnet_client: TestClient, db: Session) -> None:
    c = a_company(db)
    magnet_client.post(
        f"/api/companies/{c.id}/magnets", json={"mode": "full", "competitors": ["https://otherco.example/"]}
    )
    (m,) = magnet_client.get(f"/api/companies/{c.id}/magnets").json()
    assert m["summary"]["emails"] == 1
    report = magnet_client.get(m["link"].replace("/m/", "/api/public/magnets/")).json()
    assert report["competitors"][0]["name"] == "OtherCo"  # the one named goes first
    assert {lead["email"] for lead in report["leads"]} >= {"ana@buyer.example"}


def test_a_teaser_link_shows_only_its_first_few_leads(magnet_client: TestClient, db: Session) -> None:
    c = a_company(db)
    leads = [{"name": f"Lead {n}", "tier": "warm", "email": "x@buyer.example"} for n in range(8)]
    m = Magnet(
        company_id=c.id,
        kind="engagement",
        status="ready",
        data={"token": "t" * 43, "report": {"mode": "teaser", "leads": leads, "stats": {"fit": 20, "in_region": 8}}},
    )
    db.add(m)
    db.flush()
    body = magnet_client.get(f"/api/public/magnets/{m.id}/{'t' * 43}").json()
    assert len(body["leads"]) == magnets.TEASER_SHOWN
    assert body["more"] == 8 - magnets.TEASER_SHOWN
    assert body["fit"] == 20


@pytest.mark.parametrize(
    ("changes", "mode", "message"),
    [
        ({"anthropic_api_key": None}, "teaser", "ANTHROPIC_API_KEY"),
        ({"treg_token": SecretStr("")}, "teaser", "TREG_TOKEN"),
        ({"open_access": True}, "full", "sign-in"),
    ],
)
def test_a_build_needs_its_keys_and_emails_need_sign_in(
    magnet_client: TestClient, db: Session, changes: dict[str, Any], mode: str, message: str
) -> None:
    magnet_client.app.dependency_overrides[get_settings] = lambda: settings_with(changes)  # type: ignore[attr-defined]
    r = magnet_client.post(f"/api/companies/{a_company(db).id}/magnets", json={"mode": mode})
    assert r.status_code == 409
    assert message in r.json()["detail"]


def test_a_company_without_a_website_needs_one(magnet_client: TestClient, db: Session) -> None:
    c = f.company(db, name="No Site")
    assert magnet_client.post(f"/api/companies/{c.id}/magnets", json={}).status_code == 422
    assert magnet_client.post(f"/api/companies/{c.id}/magnets", json={"website": "nosite.example"}).status_code == 202


def test_one_build_at_a_time_unless_the_last_one_died(
    magnet_client: TestClient, db: Session, started: list[Callable[[], None]]
) -> None:
    magnet_client.app.state.magnet_runtime.spawn = started.append  # type: ignore[attr-defined]
    c = a_company(db)
    first = magnet_client.post(f"/api/companies/{c.id}/magnets", json={}).json()
    r = magnet_client.post(f"/api/companies/{c.id}/magnets", json={})
    assert r.status_code == 409
    long_ago = datetime.now(UTC) - timedelta(hours=1)
    db.execute(update(Magnet).where(Magnet.id == first["id"]).values(updated_at=long_ago))
    assert magnet_client.get(f"/api/magnets/{first['id']}").json()["status"] == "failed"  # shown as stopped
    assert magnet_client.post(f"/api/companies/{c.id}/magnets", json={}).status_code == 202
    stopped = magnet_client.get(f"/api/magnets/{first['id']}").json()
    assert (stopped["status"], stopped["error"]) == ("failed", magnets.STOPPED)


def test_a_build_given_up_on_stops_at_its_next_step_and_overwrites_nothing(
    magnet_client: TestClient, db: Session, run: FakeHarvest, started: list[Callable[[], None]]
) -> None:
    magnet_client.app.state.magnet_runtime.spawn = started.append  # type: ignore[attr-defined]
    c = a_company(db)
    first = magnet_client.post(f"/api/companies/{c.id}/magnets", json={}).json()
    long_ago = datetime.now(UTC) - timedelta(hours=1)
    db.execute(update(Magnet).where(Magnet.id == first["id"]).values(updated_at=long_ago))
    second = magnet_client.post(f"/api/companies/{c.id}/magnets", json={}).json()
    started[0]()  # the first build's worker was only slow, and wakes up now
    assert run.calls == []  # it stopped before spending anything
    assert magnet_client.get(f"/api/magnets/{first['id']}").json()["status"] == "failed"
    started[1]()
    assert magnet_client.get(f"/api/magnets/{second['id']}").json()["status"] == "ready"


def test_a_failed_build_says_why(magnet_client: TestClient, db: Session) -> None:
    magnet_client.app.state.magnet_runtime.tools = lambda: Tools(  # type: ignore[attr-defined]
        read_site=site, brain=FakeBrain("rivalco.example"), linkedin=LinkedIn(FakeHarvest()), apollo=FakeApollo({})
    )
    c = a_company(db)
    magnet_client.post(f"/api/companies/{c.id}/magnets", json={})
    (m,) = magnet_client.get(f"/api/companies/{c.id}/magnets").json()
    assert m["status"] == "failed"
    assert "LinkedIn page" in m["error"]
    assert m["link"] is None


def test_deleting_turns_the_link_off_and_stops_a_build_in_progress(
    magnet_client: TestClient, db: Session, run: FakeHarvest, started: list[Callable[[], None]]
) -> None:
    c = a_company(db)
    magnet_client.post(f"/api/companies/{c.id}/magnets", json={})
    (m,) = magnet_client.get(f"/api/companies/{c.id}/magnets").json()
    assert magnet_client.delete(f"/api/magnets/{m['id']}").status_code == 204
    assert magnet_client.get(m["link"].replace("/m/", "/api/public/magnets/")).status_code == 404

    magnet_client.app.state.magnet_runtime.spawn = started.append  # type: ignore[attr-defined]
    building = magnet_client.post(f"/api/companies/{c.id}/magnets", json={}).json()
    magnet_client.delete(f"/api/magnets/{building['id']}")
    runs_before = len(run.calls)
    started[0]()  # the build wakes up to find itself deleted
    assert len(run.calls) == runs_before  # and spends nothing
    assert db.get(Magnet, building["id"]) is None


def test_the_tracker_routes_need_sign_in(client: TestClient, db: Session) -> None:
    c = a_company(db)
    assert client.get(f"/api/companies/{c.id}/magnets").status_code == 401
    assert client.post(f"/api/companies/{c.id}/magnets", json={}).status_code == 401


def test_report_tokens_never_reach_the_log() -> None:
    assert log_path("/api/public/magnets/m123/secret-token") == "/api/public/magnets/m123/***"
    assert log_path("/m/m123/secret-token") == "/m/m123/***"
    assert log_path("/api/companies/c1/magnets") == "/api/companies/c1/magnets"
    assert log_path("/api/x\nFAKE log line\r") == "/api/x?FAKE log line?"


# ----------------------------------------------------------------------------- champion reports


@pytest.fixture
def champion_client(magnet_client: TestClient) -> TestClient:
    """Champion reports build inline against the made-up market in champion_fakes."""
    runtime: Runtime = magnet_client.app.state.magnet_runtime  # type: ignore[attr-defined]
    runtime.champions = champion_fakes.tools
    return magnet_client


def a_champion_report(client: TestClient, **body: Any) -> dict[str, Any]:
    r = client.post(
        "/api/magnets", json={"kind": "champions", "website": "https://cxhero.example", "name": "CXHero", **body}
    )
    assert r.status_code == 202, r.text
    return dict(r.json())


def test_a_champion_report_builds_and_its_link_shows_the_top_three(champion_client: TestClient, db: Session) -> None:
    started = a_champion_report(champion_client)
    assert started["kind"] == "champions"
    assert started["domain"] == "cxhero.example"

    (m,) = champion_client.get("/api/magnets", params={"kind": "champions", "domain": "cxhero.example"}).json()
    assert m["status"] == "ready"
    assert m["champions"] == {
        "champions": 4,
        "a": 2,
        "b": 1,
        "c": 1,
        "new": 4,
        "repeat": False,
        "customers": 5,
        "matched": 4,
        "movers": 20,
        "watch": 2,
        "linkedin_usd": m["champions"]["linkedin_usd"],
    }
    assert m["summary"] is None
    assert db.query(Activity).filter(Activity.kind == "magnet").one().text.startswith("CXHero: champion report ready")

    full = champion_client.get(f"/api/magnets/{m['id']}/report").json()
    assert full["kind"] == "champions"
    assert len(full["champions"]) == 4
    assert full["more"] == 0
    assert {w["name"] for w in full["watch"]} == {"Wren Stays", "Kai Nolink"}
    assert {p["reason"] for p in full["skipped_people"]} >= {"junior", "stale_move", "not_icp"}
    assert full["linkedin_usd"] > 0

    token = m["link"].rsplit("/", 1)[-1]
    champion_client.cookies.clear()  # whoever has the link isn't signed in
    shared = champion_client.get(f"/api/public/magnets/{m['id']}/{token}").json()
    assert [c["name"] for c in shared["champions"]] == ["Moe Moved", "Dana Named", "Riley Lead"]
    assert shared["more"] == 1
    assert shared["watch"] == []
    assert shared["skipped_people"] == []  # who was ruled out stays with the owner
    assert shared["linkedin_usd"] == 0
    assert shared["skipped"]["junior"] == 1


def test_only_the_owner_sees_the_full_report(champion_client: TestClient) -> None:
    a_champion_report(champion_client)
    (m,) = champion_client.get("/api/magnets").json()
    champion_client.cookies.clear()
    assert champion_client.get(f"/api/magnets/{m['id']}/report").status_code == 401


def test_a_champion_report_needs_no_apollo_and_runs_without_sign_in(champion_client: TestClient) -> None:
    no_apollo = settings_with({"apollo_api_key": SecretStr(""), "open_access": True})
    champion_client.app.dependency_overrides[get_settings] = lambda: no_apollo  # type: ignore[attr-defined]
    a_champion_report(champion_client)
    r = champion_client.post("/api/magnets", json={"website": "https://cxhero.example"})
    assert r.status_code == 409  # an engagement magnet still needs Apollo
    assert "APOLLO_API_KEY" in r.json()["detail"]


def test_a_champion_report_takes_no_full_mode_or_competitors(champion_client: TestClient) -> None:
    for extra in ({"mode": "full"}, {"competitors": ["rival.example"]}):
        r = champion_client.post(
            "/api/magnets", json={"kind": "champions", "website": "https://cxhero.example", **extra}
        )
        assert r.status_code == 422


def test_one_champion_report_at_a_time(
    champion_client: TestClient, db: Session, started: list[Callable[[], None]]
) -> None:
    runtime: Runtime = champion_client.app.state.magnet_runtime  # type: ignore[attr-defined]
    runtime.spawn = started.append  # hold the build: it stays running
    a_champion_report(champion_client)
    r = champion_client.post("/api/magnets", json={"kind": "champions", "website": "https://other.example"})
    assert r.status_code == 409
    assert "already building" in r.json()["detail"]
    # an engagement magnet isn't held up by it
    assert champion_client.post("/api/magnets", json={"website": "https://prospect.example"}).status_code == 202


def test_the_daily_limit_reserves_each_build_and_gives_back_what_it_did_not_spend(
    champion_client: TestClient, db: Session
) -> None:
    capped = settings_with({"magnet_champions_daily_usd": TREG_CAP_USD * 1.5})
    champion_client.app.dependency_overrides[get_settings] = lambda: capped  # type: ignore[attr-defined]
    a_champion_report(champion_client)
    (m,) = champion_client.get("/api/magnets").json()
    ledger = db.get(Setting, magnets.LEDGER)
    assert ledger is not None
    spent = m["champions"]["linkedin_usd"]
    assert ledger.value["usd"] == pytest.approx(spent)  # the unused part came back

    runtime: Runtime = champion_client.app.state.magnet_runtime  # type: ignore[attr-defined]
    runtime.champions = lambda: champion_fakes.tools(treg=champion_fakes.market(orgs={}))
    a_champion_report(champion_client, website="https://other.example")  # fails, and keeps its whole reservation
    db.refresh(ledger)
    assert ledger.value["usd"] == pytest.approx(spent + TREG_CAP_USD)
    r = champion_client.post("/api/magnets", json={"kind": "champions", "website": "https://cxhero.example"})
    assert r.status_code == 409
    assert "daily limit" in r.json()["detail"]


def test_a_failed_champion_report_keeps_its_reservation(champion_client: TestClient, db: Session) -> None:
    runtime: Runtime = champion_client.app.state.magnet_runtime  # type: ignore[attr-defined]
    runtime.champions = lambda: champion_fakes.tools(treg=champion_fakes.market(orgs={}))
    a_champion_report(champion_client)
    (m,) = champion_client.get("/api/magnets").json()
    assert m["status"] == "failed"
    assert "LinkedIn page" in m["error"]
    ledger = db.get(Setting, magnets.LEDGER)
    assert ledger is not None
    assert ledger.value["usd"] == pytest.approx(TREG_CAP_USD)


def test_a_second_report_for_the_same_company_marks_who_is_new(champion_client: TestClient, db: Session) -> None:
    first = a_champion_report(champion_client)
    # one test transaction gives both rows the same created_at: date the first one earlier, as it would be
    db.execute(update(Magnet).where(Magnet.id == first["id"]).values(created_at=datetime(2026, 11, 1, tzinfo=UTC)))
    a_champion_report(champion_client)
    newest, older = champion_client.get("/api/magnets", params={"domain": "cxhero.example"}).json()
    assert older["id"] == first["id"]
    assert (older["champions"]["repeat"], newest["champions"]["repeat"]) == (False, True)
    assert newest["champions"]["new"] == 0  # everyone was in the first report
    full = champion_client.get(f"/api/magnets/{newest['id']}/report").json()
    assert full["repeat"] is True
    assert not any(c["new"] for c in full["champions"])


def test_a_champion_report_for_a_tracker_company(champion_client: TestClient, db: Session) -> None:
    c = f.company(db, name="CXHero", website="https://cxhero.example")
    r = champion_client.post(f"/api/companies/{c.id}/magnets", json={"kind": "champions"})
    assert r.status_code == 202
    (m,) = champion_client.get(f"/api/companies/{c.id}/magnets").json()
    assert (m["kind"], m["status"]) == ("champions", "ready")
