"""Finding work emails and what a company does, with a fake Apollo. All names and addresses are made up."""

from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.enrich import get_finder
from app.config import get_settings
from app.enrich.apollo import Apollo, ApolloError, work_email
from app.models import MoveType
from tests import factories as f
from tests.conftest import TODAY


class FakeApollo:
    def __init__(self, emails: dict[str, str | None], about: str = "Makes made-up widgets.") -> None:
        self.emails = emails
        self.about = about
        self.calls: list[str] = []

    def match(self, *, name: str, domain: str | None, linkedin: str | None) -> dict[str, Any] | None:  # noqa: ARG002
        self.calls.append(name)
        if name == "Broken Example":
            raise ApolloError("Apollo 500")
        email = self.emails.get(name)
        return {"email": email, "email_status": "verified"} if email is not None else None

    def organization(self, domain: str) -> dict[str, Any] | None:  # noqa: ARG002
        return {"short_description": self.about}


@pytest.fixture
def apollo(signed_in: TestClient) -> FakeApollo:
    fake = FakeApollo({"Ana Example": "ana@acme.example", "Bo Example": "email_not_unlocked@domain.com"})
    signed_in.app.dependency_overrides[get_finder] = lambda: fake  # type: ignore[attr-defined]
    return fake


def test_finds_work_emails_once_and_what_the_company_does(
    signed_in: TestClient, db: Session, apollo: FakeApollo
) -> None:
    c = f.company(db, name="Acme Example", domain="acme.example")
    ana, _ = f.person(db, c, name="Ana Example")
    bo, _ = f.person(db, c, name="Bo Example")
    known, _ = f.person(db, c, name="Known Example")
    known.email = "known@acme.example"
    db.flush()

    assert signed_in.post(f"/api/companies/{c.id}/enrich").json() == {"tried": 2, "found": 1, "companies": 1}
    db.refresh(ana)
    db.refresh(bo)
    db.refresh(c)
    assert (ana.email, ana.details["email_source"], ana.details["email_status"]) == (
        "ana@acme.example",
        "apollo",
        "verified",
    )
    assert bo.email is None  # Apollo's locked placeholder isn't an email
    assert bo.details["apollo_tried"] == TODAY.isoformat()
    assert c.research["apollo_about"] == "Makes made-up widgets."
    assert signed_in.post(f"/api/companies/{c.id}/enrich").json()["tried"] == 0  # a miss isn't paid for twice
    assert apollo.calls == ["Ana Example", "Bo Example"]


def test_an_apollo_failure_stops_and_leaves_the_rest_for_later(
    signed_in: TestClient, db: Session, apollo: FakeApollo
) -> None:
    c = f.company(db, domain="acme.example")
    broken, _ = f.person(db, c, name="Broken Example")
    assert signed_in.post(f"/api/companies/{c.id}/enrich").json()["tried"] == 0
    db.refresh(broken)
    assert "apollo_tried" not in broken.details


def test_today_gets_its_companies_ready(signed_in: TestClient, db: Session, apollo: FakeApollo) -> None:
    c = f.company(db, name="Acme Example", domain="acme.example")
    f.person(db, c, name="Ana Example", day0=TODAY)
    f.move(db, c, type=MoveType.APPLY, due=TODAY)
    later = f.company(db, name="Later Example")
    f.person(db, later, name="Bo Example")  # nothing due: not on Today
    assert signed_in.post("/api/enrich/today").json() == {"tried": 1, "found": 1, "companies": 1}


def test_no_emails_while_the_tracker_is_open_or_apollo_isnt_set_up(signed_in: TestClient, db: Session) -> None:
    c = f.company(db)
    settings = get_settings()
    app = signed_in.app
    app.dependency_overrides[get_settings] = lambda: settings.model_copy(update={"open_access": True})  # type: ignore[attr-defined]
    r = signed_in.post(f"/api/companies/{c.id}/enrich")
    assert (r.status_code, r.json()["detail"]) == (409, "Turn on sign-in before finding emails.")
    app.dependency_overrides[get_settings] = lambda: settings.model_copy(update={"apollo_api_key": None})  # type: ignore[attr-defined]
    assert "APOLLO_API_KEY" in signed_in.post(f"/api/companies/{c.id}/enrich").json()["detail"]


def test_the_client_asks_for_work_emails_only() -> None:
    sent: list[httpx2.Request] = []

    def api(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        if request.url.path.endswith("/people/match"):
            return httpx2.Response(200, json={"person": {"email": "Ana@Acme.example"}})
        return httpx2.Response(429, text="rate limited")

    client = Apollo("test-key", transport=httpx2.MockTransport(api))
    hit = client.match(name="Ana Example", domain="acme.example", linkedin="https://www.linkedin.com/in/ana-example")
    assert work_email(hit) == "ana@acme.example"
    body = sent[0].read().decode()
    assert '"reveal_personal_emails":false' in body.replace(" ", "")
    assert sent[0].headers["X-Api-Key"] == "test-key"
    assert "test-key" not in str(sent[0].url)
    with pytest.raises(ApolloError, match="429"):
        client.organization("acme.example")
