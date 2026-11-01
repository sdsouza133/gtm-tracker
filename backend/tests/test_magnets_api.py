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
from app.magnet.linkedin import LinkedIn
from app.main import log_path
from app.models import Activity, Company, Magnet
from tests import factories as f
from tests.magnet_fakes import ORGS, FakeApollo, FakeBrain, FakeRunner, runner, site

KEYS = {"anthropic_api_key": "a-key", "apify_token": "an-apify-token", "apollo_api_key": "an-apollo-key"}


def settings_with(changes: dict[str, Any]) -> Settings:
    secret = {k: SecretStr(v) for k, v in KEYS.items()}
    return get_settings().model_copy(update={**secret, **changes})


@pytest.fixture
def run() -> FakeRunner:
    return runner()


@pytest.fixture
def started() -> list[Callable[[], None]]:
    return []


@pytest.fixture
def magnet_client(signed_in: TestClient, connection: Connection, run: FakeRunner) -> TestClient:
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
        ({"apify_token": SecretStr("")}, "teaser", "APIFY_TOKEN"),
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
    magnet_client: TestClient, db: Session, run: FakeRunner, started: list[Callable[[], None]]
) -> None:
    magnet_client.app.state.magnet_runtime.spawn = started.append  # type: ignore[attr-defined]
    c = a_company(db)
    first = magnet_client.post(f"/api/companies/{c.id}/magnets", json={}).json()
    long_ago = datetime.now(UTC) - timedelta(hours=1)
    db.execute(update(Magnet).where(Magnet.id == first["id"]).values(updated_at=long_ago))
    second = magnet_client.post(f"/api/companies/{c.id}/magnets", json={}).json()
    started[0]()  # the first build's worker was only slow, and wakes up now
    assert run.runs == []  # it stopped before spending anything
    assert magnet_client.get(f"/api/magnets/{first['id']}").json()["status"] == "failed"
    started[1]()
    assert magnet_client.get(f"/api/magnets/{second['id']}").json()["status"] == "ready"


def test_a_failed_build_says_why(magnet_client: TestClient, db: Session) -> None:
    magnet_client.app.state.magnet_runtime.tools = lambda: Tools(  # type: ignore[attr-defined]
        read_site=site, brain=FakeBrain("rivalco.example"), linkedin=LinkedIn(FakeRunner()), apollo=FakeApollo({})
    )
    c = a_company(db)
    magnet_client.post(f"/api/companies/{c.id}/magnets", json={})
    (m,) = magnet_client.get(f"/api/companies/{c.id}/magnets").json()
    assert m["status"] == "failed"
    assert "LinkedIn page" in m["error"]
    assert m["link"] is None


def test_deleting_turns_the_link_off_and_stops_a_build_in_progress(
    magnet_client: TestClient, db: Session, run: FakeRunner, started: list[Callable[[], None]]
) -> None:
    c = a_company(db)
    magnet_client.post(f"/api/companies/{c.id}/magnets", json={})
    (m,) = magnet_client.get(f"/api/companies/{c.id}/magnets").json()
    assert magnet_client.delete(f"/api/magnets/{m['id']}").status_code == 204
    assert magnet_client.get(m["link"].replace("/m/", "/api/public/magnets/")).status_code == 404

    magnet_client.app.state.magnet_runtime.spawn = started.append  # type: ignore[attr-defined]
    building = magnet_client.post(f"/api/companies/{c.id}/magnets", json={}).json()
    magnet_client.delete(f"/api/magnets/{building['id']}")
    runs_before = len(run.runs)
    started[0]()  # the build wakes up to find itself deleted
    assert len(run.runs) == runs_before  # and spends nothing
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
