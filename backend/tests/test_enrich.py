"""Finding work emails and what a company does, with a fake Apollo. All names and addresses are made up."""

from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.api.enrich import get_finder
from app.config import get_settings
from app.enrich.apollo import Apollo, ApolloError, work_email
from app.models import Company, MoveType, Person
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


def test_today_reaches_past_companies_already_looked_up(
    signed_in: TestClient, db: Session, apollo: FakeApollo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.api.enrich.TODAY_COMPANIES", 1)
    for name, who in (("Acme Example", "Ana Example"), ("Bolt Example", "Bo Example")):
        c = f.company(db, name=name, domain=f"{name.split()[0].lower()}.example")
        f.person(db, c, name=who, day0=TODAY)
        f.move(db, c, type=MoveType.APPLY, due=TODAY)
    assert signed_in.post("/api/enrich/today").json()["tried"] == 1
    assert signed_in.post("/api/enrich/today").json()["tried"] == 1  # the next company, not the first one again
    assert sorted(apollo.calls) == ["Ana Example", "Bo Example"]
    assert signed_in.post("/api/enrich/today").json() == {"tried": 0, "found": 0, "companies": 0}


def test_an_email_typed_in_during_the_lookup_wins(signed_in: TestClient, db: Session, apollo: FakeApollo) -> None:
    c = f.company(db, domain="acme.example")
    ana, _ = f.person(db, c, name="Ana Example")
    db.flush()

    def typed_meanwhile(**_: Any) -> dict[str, Any]:
        # behind the session's back, as another request would: only a re-read sees it
        db.execute(
            update(Person).where(Person.id == ana.id).values(email="typed@acme.example"),
            execution_options={"synchronize_session": False},
        )
        return {"email": "ana@acme.example"}

    apollo.match = typed_meanwhile  # type: ignore[method-assign]
    assert signed_in.post(f"/api/companies/{c.id}/enrich").json()["found"] == 0
    db.refresh(ana)
    assert (ana.email, ana.details["apollo_tried"]) == ("typed@acme.example", TODAY.isoformat())


def test_someone_with_nothing_to_find_them_by_waits_until_there_is(
    signed_in: TestClient, db: Session, apollo: FakeApollo
) -> None:
    c = f.company(db, domain=None)
    ana, _ = f.person(db, c, name="Ana Example")
    db.flush()
    assert signed_in.post(f"/api/companies/{c.id}/enrich").json()["tried"] == 0
    db.refresh(ana)
    assert "apollo_tried" not in ana.details
    ana.linkedin = "https://www.linkedin.com/in/ana-example"
    db.flush()
    assert signed_in.post(f"/api/companies/{c.id}/enrich").json() == {"tried": 1, "found": 1, "companies": 1}


def test_research_edited_during_the_company_lookup_wins(signed_in: TestClient, db: Session, apollo: FakeApollo) -> None:
    c = f.company(db, domain="acme.example")
    db.flush()

    def edited_meanwhile(domain: str) -> dict[str, Any]:
        db.execute(
            update(Company).where(Company.id == c.id).values(research={"pmf_reason": "Typed by hand."}),
            execution_options={"synchronize_session": False},
        )
        return {"short_description": "From Apollo."}

    apollo.organization = edited_meanwhile  # type: ignore[method-assign]
    signed_in.post(f"/api/companies/{c.id}/enrich")
    db.refresh(c)
    assert c.research == {"pmf_reason": "Typed by hand."}


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


def test_the_client_only_trusts_sure_matches() -> None:
    sent: list[httpx2.Request] = []

    def api(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200, json={"person": {"email": "x@acme.example", "match_confidence": "low"}})

    client = Apollo("test-key", transport=httpx2.MockTransport(api))
    assert client.match(name="Ana Example", domain=None, linkedin=None) is None  # a name alone isn't asked about
    assert sent == []
    assert client.match(name="Ana Example", domain="acme.example", linkedin=None) is None  # Apollo wasn't sure


@pytest.mark.parametrize(
    "reply",
    [
        lambda r: (_ for _ in ()).throw(httpx2.ReadTimeout("slow", request=r)),
        lambda _: httpx2.Response(200, text="<html>oops</html>"),
    ],
)
def test_the_client_turns_timeouts_and_garbage_into_apollo_errors(reply: Any) -> None:
    client = Apollo("test-key", transport=httpx2.MockTransport(reply))
    with pytest.raises(ApolloError):
        client.organization("acme.example")
