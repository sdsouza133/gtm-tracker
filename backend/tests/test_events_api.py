"""The events tool's API: starting a run, the plan, following it, the list, and the switches. Runs are set up as the
worker would leave them; the worker itself is tested in tests/events."""

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.events import get_now
from app.config import get_settings
from app.events.config import EventsSettings, get_events_settings
from app.events.models import BudgetDay, Event, Job, Lead, Person, Post, Run, RunStatus
from app.events.pipeline.analyze import ANALYZE_SITE
from app.events.pipeline.collect import COLLECT_EVENT
from app.events.pipeline.keywords import build_queries
from app.events.providers.fakes import FakeLlm
from app.events.providers.types import FetchedPage
from tests import factories as f
from tests.conftest import NOON
from tests.events.factories import make_run

FAKES = EventsSettings(providers="fake")


@pytest.fixture
def events_client(signed_in: TestClient) -> TestClient:
    overrides = signed_in.app.dependency_overrides  # type: ignore[attr-defined]
    overrides[get_events_settings] = lambda: FAKES
    overrides[get_now] = lambda: NOON
    return signed_in


def planned_run(db: Session, **kw: Any) -> Run:
    """A run as analyze leaves it: the ICP read from the site, and the events found, waiting for approval."""
    llm = FakeLlm()
    home = FetchedPage("https://acme.example/", 200, "Acme Analytics | Home", None, "")
    analysis = llm.analyze_site([home]).value
    found = llm.find_events(analysis, today=NOON.date()).value
    run = make_run(db, status=RunStatus.AWAITING_APPROVAL, **kw)
    run.icp = analysis.model_dump(mode="json")
    run.suggested_events = [
        {**event.model_dump(mode="json"), "queries": build_queries(event, today=NOON.date())} for event in found
    ]
    db.flush()
    return run


def plan_body(run: dict[str, Any], *, picks: list[int], approve: bool = False) -> dict[str, Any]:
    plan = run["plan"]
    events = [{"picked": e["index"] in picks, "queries": e["queries"]} for e in plan["events"]]
    return {"icp": plan["icp"], "events": events, "approve": approve}


def jobs(db: Session, kind: str) -> list[Job]:
    return list(db.scalars(select(Job).where(Job.kind == kind)))


# ---------------------------------------------------------------------------------------------- starting a run
def test_a_run_starts_from_a_website_and_reads_it_first(events_client: TestClient, db: Session) -> None:
    company = f.company(db, name="Acme")
    r = events_client.post("/api/events/runs", json={"website": "https://www.Acme.com/about", "company_id": company.id})
    assert r.status_code == 201
    run = r.json()
    assert (run["status"], run["label"], run["detail"]) == (
        "analyzing",
        "Getting the plan ready",
        "Reading the website",
    )
    assert (run["domain"], run["company_name"], run["working"]) == ("acme.com", "Acme", True)
    assert run["progress"]["steps"][0] == "Reading acme.com"
    assert run["plan"] is None
    [job] = jobs(db, ANALYZE_SITE)
    assert job.payload == {"run_id": run["id"]}

    home = events_client.get("/api/events").json()
    assert [listed["id"] for listed in home["runs"]] == [run["id"]]
    assert home["today"]["runs_started"] == 1
    assert home["queue"]["due"] == 1
    assert events_client.get("/api/events", params={"company_id": "c-nobody"}).json()["runs"] == []


@pytest.mark.parametrize(
    ("body", "code", "says"),
    [
        ({"website": "not a website"}, 422, "Enter the company's website"),
        ({"website": "http://localhost:8000"}, 422, "Enter the company's website"),
        ({"website": "acme.com", "company_id": "c-nobody"}, 404, "isn't in the tracker"),
    ],
)
def test_a_run_needs_a_public_website(
    events_client: TestClient, db: Session, body: dict[str, Any], code: int, says: str
) -> None:
    r = events_client.post("/api/events/runs", json=body)
    assert r.status_code == code
    assert says in r.json()["detail"]
    assert db.scalars(select(Run)).all() == []


def test_without_its_keys_no_run_starts(events_client: TestClient) -> None:
    real = EventsSettings(providers="real", anthropic_api_key="a-key")
    events_client.app.dependency_overrides[get_events_settings] = lambda: real  # type: ignore[attr-defined]
    assert events_client.get("/api/events").json()["missing"] == ["APIFY_TOKEN", "APOLLO_API_KEY"]
    r = events_client.post("/api/events/runs", json={"website": "acme.com"})
    assert r.status_code == 409
    assert "APIFY_TOKEN, APOLLO_API_KEY" in r.json()["detail"]


def test_new_runs_can_be_held_and_let_go(events_client: TestClient) -> None:
    assert events_client.put("/api/events/new-runs", json={"paused": True}).status_code == 204
    assert events_client.get("/api/events").json()["paused"] is True
    r = events_client.post("/api/events/runs", json={"website": "acme.com"})
    assert (r.status_code, r.json()["detail"]) == (409, "New runs are paused. Turn them back on to start one.")
    assert events_client.put("/api/events/new-runs", json={"paused": False}).status_code == 204
    assert events_client.post("/api/events/runs", json={"website": "acme.com"}).status_code == 201


def test_the_setting_holds_new_runs_whatever_the_switch_says(events_client: TestClient) -> None:
    held = EventsSettings(providers="fake", pause_new_runs=True)
    events_client.app.dependency_overrides[get_events_settings] = lambda: held  # type: ignore[attr-defined]
    home = events_client.get("/api/events").json()
    assert (home["paused"], home["paused_by_setting"]) == (True, True)
    assert events_client.post("/api/events/runs", json={"website": "acme.com"}).status_code == 409


def test_without_sign_in_the_tool_is_off(events_client: TestClient, db: Session) -> None:
    run = planned_run(db)
    open_settings = get_settings().model_copy(update={"open_access": True})
    events_client.app.dependency_overrides[get_settings] = lambda: open_settings  # type: ignore[attr-defined]
    home = events_client.get("/api/events").json()
    assert (home["open_access"], home["runs"]) == (True, [])
    for method, path in [
        ("POST", "/api/events/runs"),
        ("GET", f"/api/events/runs/{run.id}"),
        ("GET", f"/api/events/runs/{run.id}/leads"),
        ("POST", f"/api/events/runs/{run.id}/cancel"),
        ("PUT", "/api/events/new-runs"),
    ]:
        r = events_client.request(method, path, json={"website": "acme.com", "paused": True})
        assert r.status_code == 409, path
        assert "OPEN_ACCESS" in r.json()["detail"]


# ---------------------------------------------------------------------------------------------------- the plan
def test_the_plan_shows_the_icp_and_the_events_with_the_first_three_picked(
    events_client: TestClient, db: Session
) -> None:
    run = planned_run(db)
    shown = events_client.get(f"/api/events/runs/{run.id}").json()
    assert (shown["status"], shown["working"], shown["progress"]) == ("awaiting_approval", False, None)
    plan = shown["plan"]
    assert plan["company_name"] == "Acme Analytics"
    assert plan["icp"]["personas"]
    assert (plan["max_picked"], plan["max_queries"]) == (3, 4)
    assert [event["picked"] for event in plan["events"]][:4] == [True, True, True, False]
    assert all(event["queries"] for event in plan["events"])
    past = [event for event in plan["events"] if event["past"]]
    assert past
    assert all((event["end_date"] or event["start_date"]) < NOON.date().isoformat() for event in past)


def test_the_plan_saves_as_edited_and_approving_starts_the_search(events_client: TestClient, db: Session) -> None:
    run = planned_run(db)
    shown = events_client.get(f"/api/events/runs/{run.id}").json()
    body = plan_body(shown, picks=[1, 3])
    body["icp"]["summary"] = "Revenue teams at mid-size B2B software companies."
    body["events"][1]["queries"] = ['"RevOps Summit" speaking', '"RevOps Summit" speaking', "  "]  # dupes and blanks go
    saved = events_client.put(f"/api/events/runs/{run.id}/plan", json=body).json()
    assert saved["status"] == "awaiting_approval"
    assert saved["plan"]["icp"]["summary"] == "Revenue teams at mid-size B2B software companies."
    assert [event["index"] for event in saved["plan"]["events"] if event["picked"]] == [1, 3]
    assert saved["plan"]["events"][1]["queries"] == ['"RevOps Summit" speaking']
    assert jobs(db, COLLECT_EVENT) == []

    approved = events_client.put(f"/api/events/runs/{run.id}/plan", json={**body, "approve": True})
    assert approved.status_code == 200
    assert (approved.json()["status"], approved.json()["working"]) == ("collecting", True)
    assert approved.json()["found"] == {"posts": 0, "people": 0, "emails": 0, "percent": 2}
    assert len(jobs(db, COLLECT_EVENT)) == 2
    again = events_client.put(f"/api/events/runs/{run.id}/plan", json={**body, "approve": True})
    assert (again.status_code, again.json()["detail"]) == (409, "This run's plan can't be changed any more.")
    assert len(jobs(db, COLLECT_EVENT)) == 2  # a second click starts nothing more


@pytest.mark.parametrize(
    ("change", "says"),
    [
        ("none_picked", "Pick at least one event"),
        ("four_picked", "Pick up to 3 events."),
        ("no_searches", "1 to 4 searches"),
        ("too_many_searches", "1 to 4 searches"),
        ("one_event_short", "The plan changed while you were editing it"),
    ],
)
def test_a_plan_that_cant_run_is_refused(events_client: TestClient, db: Session, change: str, says: str) -> None:
    run = planned_run(db)
    shown = events_client.get(f"/api/events/runs/{run.id}").json()
    body = plan_body(shown, picks=[0], approve=True)
    if change == "none_picked":
        body = plan_body(shown, picks=[], approve=True)
    elif change == "four_picked":
        body = plan_body(shown, picks=[0, 1, 2, 3], approve=True)
    elif change == "no_searches":
        body["events"][0]["queries"] = []
    elif change == "too_many_searches":
        body["events"][0]["queries"] = [f'"Summit" query {n}' for n in range(5)]
    else:
        body["events"] = body["events"][:-1]
    r = events_client.put(f"/api/events/runs/{run.id}/plan", json=body)
    assert r.status_code == 422
    assert says in r.json()["detail"]
    db.expire_all()
    assert db.get(Run, run.id).status == RunStatus.AWAITING_APPROVAL  # type: ignore[union-attr]


def test_an_icp_that_isnt_one_is_refused_before_anything_is_saved(events_client: TestClient, db: Session) -> None:
    run = planned_run(db)
    body = plan_body(events_client.get(f"/api/events/runs/{run.id}").json(), picks=[0])
    body["icp"]["personas"] = []
    assert events_client.put(f"/api/events/runs/{run.id}/plan", json=body).status_code == 422


def test_an_event_you_know_is_added_with_searches_written_for_it(events_client: TestClient, db: Session) -> None:
    run = planned_run(db)
    added = events_client.post(
        f"/api/events/runs/{run.id}/events",
        json={"name": "  Demand Gen   Live ", "day": "2026-11-12", "url": "demandgen.example"},
    )
    assert added.status_code == 200
    events = added.json()["plan"]["events"]
    mine = events[-1]
    assert (mine["name"], mine["own"], mine["url"], mine["start_date"]) == (
        "Demand Gen Live",
        True,
        "https://demandgen.example",
        "2026-11-12",
    )
    assert mine["picked"] is False  # three are picked already: unpick one to search it
    assert mine["queries"]
    assert [event["picked"] for event in events[:3]] == [True, True, True]

    again = events_client.post(
        f"/api/events/runs/{run.id}/events", json={"name": "Demand Gen Live", "day": "2026-11-12"}
    )
    assert (again.status_code, again.json()["detail"]) == (422, "That event is already in the plan.")


def test_an_event_added_is_picked_when_there_is_room(events_client: TestClient, db: Session) -> None:
    run = planned_run(db)
    body = plan_body(events_client.get(f"/api/events/runs/{run.id}").json(), picks=[0])
    events_client.put(f"/api/events/runs/{run.id}/plan", json=body)
    added = events_client.post(f"/api/events/runs/{run.id}/events", json={"name": "Demand Gen Live"}).json()
    assert added["plan"]["events"][-1]["picked"] is True


@pytest.mark.parametrize(
    ("body", "says"),
    [
        ({"name": "Demand Gen Live", "url": "not a link"}, "Enter the event's web address"),
        ({"name": "x" * 150}, "in up to 120 characters"),
    ],
)
def test_an_event_that_isnt_one_is_refused(
    events_client: TestClient, db: Session, body: dict[str, Any], says: str
) -> None:
    run = planned_run(db)
    r = events_client.post(f"/api/events/runs/{run.id}/events", json=body)
    assert r.status_code == 422
    assert says in r.json()["detail"]


def test_up_to_three_events_of_your_own(events_client: TestClient, db: Session) -> None:
    run = planned_run(db)
    for n in range(3):
        assert events_client.post(f"/api/events/runs/{run.id}/events", json={"name": f"Meetup {n}"}).status_code == 200
    r = events_client.post(f"/api/events/runs/{run.id}/events", json={"name": "Meetup 4"})
    assert (r.status_code, r.json()["detail"]) == (422, "You can add up to 3 events of your own.")


# -------------------------------------------------------------------------------------------- following a run
def test_a_run_can_be_canceled_until_it_finishes(events_client: TestClient, db: Session) -> None:
    working = make_run(db, status=RunStatus.QUALIFYING)
    canceled = events_client.post(f"/api/events/runs/{working.id}/cancel").json()
    assert (canceled["status"], canceled["detail"], canceled["working"]) == (
        "canceled",
        "Canceled before it finished.",
        False,
    )
    assert canceled["error"] == "canceled from the Events page"

    ready = make_run(db, status=RunStatus.READY)
    assert events_client.post(f"/api/events/runs/{ready.id}/cancel").json()["status"] == "ready"
    assert events_client.post(f"/api/events/runs/{uuid.uuid4()}/cancel").status_code == 404


def test_a_waiting_run_says_why(events_client: TestClient, db: Session) -> None:
    run = make_run(db, status=RunStatus.WAITING_FOR_BUDGET)
    run.status_detail = "Today's spend cap is reached. The search will go on automatically after midnight UTC."
    db.flush()
    shown = events_client.get(f"/api/events/runs/{run.id}").json()
    assert shown["label"] == "Waiting for tomorrow's budget"
    assert shown["progress"]["note"].startswith("Today's spend cap is reached")


def test_a_missing_run_is_not_found(events_client: TestClient) -> None:
    r = events_client.get(f"/api/events/runs/{uuid.uuid4()}")
    assert r.status_code == 404


# -------------------------------------------------------------------------------------------------------- list
def listed_run(db: Session) -> Run:
    """A finished run with three people on its list (and one left out)."""
    run = make_run(db, status=RunStatus.READY)
    run.results_expire_at = NOON + timedelta(days=30)
    run.leads_count = 3
    summit = Event(key=f"summit-{uuid.uuid4().hex[:6]}", name="Pipeline Summit")
    db.add(summit)
    db.flush()
    for n, (name, attendance, score, included) in enumerate(
        [
            ("Ann Example", "attending", 80, True),
            ("Bea Example", "speaking", 80, True),
            ("Cal Example", "attended", 95, True),
            ("Dee Example", "speaking", 10, False),
        ]
    ):
        person = Person(
            linkedin_url=f"https://www.linkedin.com/in/{name.split()[0].lower()}-{uuid.uuid4().hex[:6]}",
            name=name,
            title="VP Marketing",
            company_name="Northwind",
            email=f"{name.split()[0].lower()}@northwind.example",
            email_status="verified",
        )
        post = Post(
            id=f"post-{uuid.uuid4().hex[:8]}-{n}",
            url="javascript:alert(1)" if n == 0 else "https://www.linkedin.com/posts/x",
        )
        db.add_all([person, post])
        db.flush()
        db.add(
            Lead(
                run_id=run.id,
                person_id=person.id,
                event_id=summit.id,
                post_id=post.id,
                attendance=attendance,
                icp_score=score,
                icp_reasons=["title matches 'marketing'"],
                included=included,
            )
        )
    db.flush()
    return run


def test_a_finished_run_s_list_is_best_first(events_client: TestClient, db: Session) -> None:
    run = listed_run(db)
    shown = events_client.get(f"/api/events/runs/{run.id}").json()
    assert (shown["label"], shown["leads"], shown["working"]) == ("List ready", 3, False)
    listed = events_client.get(f"/api/events/runs/{run.id}/leads").json()
    assert [lead["name"] for lead in listed] == ["Cal Example", "Bea Example", "Ann Example"]  # score, then speakers
    assert [lead["attendance"] for lead in listed] == ["Went", "Speaking", "Going"]
    ann = listed[-1]
    assert (ann["email"], ann["event"], ann["post"]) == (
        "ann@northwind.example",
        "Pipeline Summit",
        "",
    )  # no script links
    assert ann["linkedin"].startswith("https://www.linkedin.com/in/ann-")


def test_an_expired_list_is_gone(events_client: TestClient, db: Session) -> None:
    run = listed_run(db)
    run.results_expire_at = NOON - timedelta(minutes=1)
    db.flush()
    r = events_client.get(f"/api/events/runs/{run.id}/leads")
    assert (r.status_code, r.json()["detail"]) == (
        410,
        "This list has expired, and its personal data has been deleted.",
    )


def test_a_run_still_working_has_no_list(events_client: TestClient, db: Session) -> None:
    run = make_run(db, status=RunStatus.ENRICHING)
    assert events_client.get(f"/api/events/runs/{run.id}/leads").status_code == 409


def test_spend_today_counts_against_the_daily_cap(events_client: TestClient, db: Session) -> None:
    db.add(BudgetDay(day=NOON.date(), spent_usd=Decimal("1.25"), reserved_usd=Decimal("0.50")))
    db.flush()
    today = events_client.get("/api/events").json()["today"]
    assert (today["spent_usd"], today["reserved_usd"], today["cap_usd"]) == (1.25, 0.5, 20.0)
