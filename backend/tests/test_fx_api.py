from datetime import date, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Activity, Prospect
from tests.conftest import TODAY


def prospect(pid: str, day: date = TODAY, rank: int = 1, **extra: Any) -> dict[str, Any]:
    return {
        "id": pid,
        "day": day.isoformat(),
        "rank": rank,
        "name": f"{pid.title()} Example",
        "domain": f"{pid}.example",
        "round": "$4M Seed",
        "hq": "Toronto",
        "dmarc": "none",
        "why_now": "Just raised",
        "offer": "An outbound system",
        "pvp": "A list of 50 accounts",
        "research": {"one_liner": f"{pid} does billing", "interview_hooks": ["Saw your launch"]},
        "people": [{"key": "ana", "name": "Ana Example", "title": "CEO"}, {"key": "bo", "name": "Bo Example"}],
        **extra,
    }


def sync(client: TestClient, *items: dict[str, Any]) -> dict[str, int]:
    r = client.put("/api/fx/prospects", json={"prospects": list(items)})
    assert r.status_code == 200, r.text
    result: dict[str, int] = r.json()
    return result


def test_sync_adds_then_refreshes_research_and_keeps_your_progress(signed_in: TestClient, db: Session) -> None:
    assert sync(signed_in, prospect("acme")) == {"added": 1, "updated": 0}
    signed_in.patch("/api/fx/prospects/acme", json={"touch": {"person": "ana", "kind": "connect"}, "my_notes": "hi"})
    assert sync(signed_in, prospect("acme", why_now="Hiring a CRO")) == {"added": 0, "updated": 1}
    assert sync(signed_in, prospect("acme", why_now="Hiring a CRO")) == {"added": 0, "updated": 0}
    d = signed_in.get("/api/fx/prospects/acme").json()
    assert (d["why_now"], d["my_notes"], d["touches"]) == ("Hiring a CRO", "hi", {"ana": {"connect": "2026-10-26"}})
    assert db.scalar(select(Activity.text).where(Activity.text.like("Fractional list%"))) == (
        "Fractional list: 1 new prospect"
    )


def test_the_board(signed_in: TestClient) -> None:
    sync(
        signed_in,
        prospect("old", day=TODAY - timedelta(days=3)),
        prospect("now", rank=2),
        prospect("next", day=TODAY + timedelta(days=1)),
        prospect("past", day=TODAY - timedelta(days=7)),
    )
    signed_in.patch("/api/settings", json={"fx_goals": {"default": 2}})
    signed_in.patch("/api/fx/prospects/past", json={"touch": {"person": "ana", "kind": "email"}, "when": "2026-10-19"})
    signed_in.patch("/api/fx/prospects/now", json={"touch": {"person": "bo", "kind": "dm"}})
    b = signed_in.get("/api/fx/board").json()
    assert (b["goal"], b["hits_today"]) == (2, 1)
    assert [c["id"] for c in b["carried_over"]] == ["old"]
    assert b["todays_list"] == []
    assert [c["id"] for c in b["reached_today"]] == ["now"]
    assert [c["id"] for c in b["follow_ups_due"]] == ["past"]
    assert b["follow_ups_due"][0]["next_step"] == "Follow-up 1, overdue 4 days"  # due Thu 22nd
    assert ([c["id"] for c in b["coming_up"]], b["coming_up_total"]) == (["next"], 1)
    s = b["stats"]
    assert (s["xp"], s["level"]["name"], s["funnel"]["reached"]) == (6, "Rookie", 2)
    assert len(s["heat"]) == 20
    assert next(x for x in s["badges"] if x["key"] == "first_hit")["earned"] is True
    card = b["reached_today"][0]
    assert (card["touched"], card["one_liner"], card["stage"]) == (["bo"], "now does billing", "waiting")


def test_pipeline_and_search(signed_in: TestClient) -> None:
    sync(signed_in, prospect("acme"), prospect("beta", rank=2), prospect("gamma", rank=3))
    signed_in.patch("/api/fx/prospects/beta", json={"touch": {"person": "ana", "kind": "connect"}})
    signed_in.patch("/api/fx/prospects/gamma", json={"status": "lost", "lost_reason": "Too early"})
    cols = {c["key"]: [i["id"] for i in c["items"]] for c in signed_in.get("/api/fx/pipeline").json()}
    assert (cols["untouched"], cols["waiting"], cols["closed"]) == (["acme"], ["beta"], ["gamma"])
    page = signed_in.get("/api/fx/prospects", params={"q": "ana example"}).json()
    assert page["total"] == 3  # people's names are searchable
    assert signed_in.get("/api/fx/prospects", params={"show": "in_play"}).json()["items"][0]["id"] == "beta"
    assert signed_in.get("/api/fx/prospects", params={"show": "closed", "q": "gamma"}).json()["total"] == 1
    assert signed_in.get("/api/fx/prospects", params={"show": "untouched", "limit": 1}).json()["total"] == 1


def test_changes_and_their_checks(signed_in: TestClient, db: Session) -> None:
    sync(signed_in, prospect("acme"))
    r = signed_in.patch(
        "/api/fx/prospects/acme",
        json={"step": {"name": "won"}, "day_override": "2026-10-28", "draft": "Hi Ana"},
    )
    d = r.json()
    assert (d["status"], d["stage"], d["day_override"], d["draft"]) == ("won", "won", "2026-10-28", "Hi Ana")
    d = signed_in.patch("/api/fx/prospects/acme", json={"status": "open", "day_override": None}).json()
    assert (d["status"], d["steps"], d["day_override"]) == ("open", {}, None)
    bad = [
        {"touch": {"person": "zed", "kind": "dm"}},
        {"touch": {"person": "ana", "kind": "fax"}},
        {"step": {"name": "dance"}},
        {"status": "maybe"},
        {"step": {"name": "call"}, "when": "2026-12-01"},
    ]
    codes = [signed_in.patch("/api/fx/prospects/acme", json=b).status_code for b in bad]
    assert codes == [422, 422, 422, 422, 422]
    assert signed_in.get("/api/fx/prospects/nope").status_code == 404
    lines = db.scalars(select(Activity.text).where(Activity.kind == "fractional")).all()
    assert "Acme Example: signed as a client" in lines
    assert db.get(Prospect, "acme") is not None


def test_sync_validates_input(signed_in: TestClient) -> None:
    assert signed_in.put("/api/fx/prospects", json={"prospects": [prospect("bad id!")]}).status_code == 422
    goals = signed_in.patch("/api/settings", json={"fx_goals": {"default": 10, "2026-10-31": 0}})
    assert goals.status_code == 200
    assert signed_in.patch("/api/settings", json={"fx_goals": {"someday": 3}}).status_code == 422
    assert signed_in.patch("/api/settings", json={"fx_goals": {"default": 99}}).status_code == 422
