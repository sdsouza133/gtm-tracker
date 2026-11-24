"""LinkedIn links and verified emails from Apollo, with a fake Apollo. Every name, company, link and address here is
made up."""

import logging
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Connection, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.api.enrich import get_contact_finder
from app.config import get_settings
from app.enrich.apollo import Apollo, ApolloError
from app.models import Activity, Person, Prospect
from app.radar import run as radar
from app.services import contacts, fx_board
from tests import factories as f
from tests.conftest import TODAY
from tests.radar_fakes import FakeWeb
from tests.test_fx_api import prospect, sync

ACME = "acme.example"


def hit(first: str, last: str, *, domain: str | None = ACME, org: str = "Acme", **extra: Any) -> dict[str, Any]:
    """An Apollo person, as /people/bulk_match sends one back (with an email, which is never kept)."""
    return {
        "first_name": first,
        "last_name": last,
        "name": f"{first} {last}",
        "linkedin_url": f"http://www.linkedin.com/in/{first}-{last}".lower(),
        "email": f"{first}@{domain or 'elsewhere.example'}".lower(),
        "match_confidence": "high",
        "organization": {"name": org, "primary_domain": domain},
        **extra,
    }


def link(first: str, last: str) -> str:
    return f"https://www.linkedin.com/in/{first}-{last}".lower()


class FakeApollo:
    """Answers by the name asked about, and keeps every request."""

    def __init__(self, people: dict[str, dict[str, Any] | None] | None = None) -> None:
        self.people = people or {}
        self.requests: list[list[dict[str, Any]]] = []

    def bulk_match(self, details: list[dict[str, Any]]) -> list[dict[str, Any] | None]:
        self.requests.append(details)
        return [self.people.get(d["name"]) for d in details]

    @property
    def asked(self) -> list[str]:
        return [d["name"] for r in self.requests for d in r]


@pytest.fixture
def apollo(signed_in: TestClient) -> FakeApollo:
    fake = FakeApollo()
    signed_in.app.dependency_overrides[get_contact_finder] = lambda: fake  # type: ignore[attr-defined]
    return fake


# ----------------------------------------------------------------------------- whose link it is


@pytest.mark.parametrize(
    ("name", "company", "domain", "found", "expected"),
    [
        ("Ana Example", "Acme", ACME, hit("Ana", "Example"), link("Ana", "Example")),
        # Apollo once called a stranger with another last name a sure match
        ("Ana Example", "Acme", ACME, hit("Ana", "Stranger", domain=None, org="Some Clinic"), None),
        ("Ana Example", "Acme", ACME, hit("Ana", "Stranger"), None),
        ("Ana Example", "Acme", ACME, hit("Example", "Example"), None),  # our surname isn't a first name
        ("Ana Example", "Acme", ACME, hit("Ana", "Example", domain="other.example", org="Other"), None),
        # Apollo's own doubt doesn't matter when the name and the company agree
        ("Ana Example", "Acme", ACME, hit("Ana", "Example", match_confidence="low"), link("Ana", "Example")),
        ("William (Will) Example", "Acme", ACME, hit("Will", "Example"), link("Will", "Example")),
        ("Will Example", "Acme", ACME, hit("William", "Example"), link("William", "Example")),
        ("Isa Meyer Example", "Acme", ACME, hit("Isa", "Example"), link("Isa", "Example")),
        ("Sébastien Exemple", "Acme", ACME, hit("Sebastien", "Exemple"), link("Sebastien", "Exemple")),
        ("Ana Example", "Acme", "eu.acme.example", hit("Ana", "Example"), link("Ana", "Example")),
        # no domain from Apollo: the employer's name has to carry the company's
        (
            "Ana Example",
            "Acme (Holdings)",
            ACME,
            hit("Ana", "Example", domain=None, org="Acme Health Network"),
            link("Ana", "Example"),
        ),
        ("Ana Example", "Acme", ACME, hit("Ana", "Example", domain=None, org="Other Health"), None),
        ("Ana", "Acme", ACME, hit("Ana", "Example"), None),  # one word could be anyone
        ("Zac E.", "Acme", ACME, hit("Zac", "E."), None),  # an initial can't be checked
        (
            "Ana Example",
            "Acme",
            ACME,
            hit("Ana", "Example", linkedin_url="https://www.linkedin.com/company/acme"),
            None,
        ),
        ("Ana Example", "Acme", ACME, hit("Ana", "Example", linkedin_url=None), None),
        ("Ana Example", "Acme", ACME, None, None),
    ],
)
def test_a_link_is_kept_only_when_the_name_and_the_company_agree(
    name: str, company: str, domain: str, found: dict[str, Any] | None, expected: str | None
) -> None:
    assert contacts.verified_contact(name, company, domain, found).link == expected


@pytest.mark.parametrize(
    ("found", "email"),
    [
        (hit("Ana", "Example", email_status="verified"), "ana@acme.example"),
        (hit("Ana", "Example", email_status="Verified", email="Ana@EU.Acme.example"), "ana@eu.acme.example"),
        (hit("Ana", "Example", email_status="guessed"), None),  # only verified addresses
        (hit("Ana", "Example", email_status="unavailable"), None),
        (hit("Ana", "Example"), None),  # no status at all
        (hit("Ana", "Example", email_status="verified", email="ana@personal.example"), None),  # not at the company
        (hit("Ana", "Example", email_status="verified", email="email_not_unlocked@domain.com"), None),
        (hit("Ana", "Stranger", email_status="verified"), None),  # someone else's address
    ],
)
def test_an_email_is_kept_only_when_verified_and_at_the_company(found: dict[str, Any], email: str | None) -> None:
    assert contacts.verified_contact("Ana Example", "Acme", ACME, found).email == email


@pytest.mark.parametrize("employer", ["tenant.mail.example", "mail.example"])  # Apollo's domain for the employer
def test_an_address_above_the_company_domain_is_not_its_own(employer: str) -> None:
    found = hit("Ana", "Example", domain=employer, email_status="verified", email="ana@mail.example")
    contact = contacts.verified_contact("Ana Example", "Acme", "tenant.mail.example", found)
    assert (contact.link, contact.email) == (link("Ana", "Example"), None)


def test_links_come_back_in_one_shape() -> None:
    assert (
        contacts.profile_link("http://linkedin.com/in/ana-example?trk=feed")
        == "https://www.linkedin.com/in/ana-example"
    )
    assert contacts.profile_link("https://ca.linkedin.com/in/ana-example/") == "https://www.linkedin.com/in/ana-example"
    assert contacts.profile_link("https://example.com/in/ana") is None


# ----------------------------------------------------------------------------- the board


def test_people_on_the_board_get_their_link_and_verified_email_once(
    signed_in: TestClient, db: Session, apollo: FakeApollo
) -> None:
    c = f.company(db, name="Acme", domain=ACME)
    ana, _ = f.person(db, c, name="Ana Example")
    bo, _ = f.person(db, c, name="Bo Example")
    cy, _ = f.person(db, c, name="Cy Example")
    cy.linkedin = "https://www.linkedin.com/in/cy-typed"  # a link but no email: still asked, for the email
    done, _ = f.person(db, c, name="Dee Example")
    done.linkedin, done.email = "https://www.linkedin.com/in/dee", "dee@acme.example"  # nothing missing
    gone, _ = f.person(db, c, name="Di Example")
    gone.left = True
    f.person(db, c, name="Ed")  # a first name alone isn't asked about
    elsewhere = f.company(db, name="No Site")
    f.person(db, elsewhere, name="Fay Example")  # no domain: nothing to check the company against
    db.flush()
    apollo.people = {
        "Ana Example": hit("Ana", "Example", email_status="verified"),
        "Bo Example": hit("Bo", "Stranger", email_status="verified"),  # someone else: nothing of theirs is kept
        "Cy Example": hit("Cy", "Example", email_status="guessed"),  # not verified: no email
    }

    assert signed_in.post("/api/people/contacts").json() == {"tried": 3, "links": 1, "emails": 1, "left": 0}
    assert sorted(apollo.asked) == ["Ana Example", "Bo Example", "Cy Example"]
    for p in (ana, bo, cy):
        db.refresh(p)
    assert (ana.linkedin, ana.email) == (link("Ana", "Example"), "ana@acme.example")
    assert {k: ana.details[k] for k in ("contact_tried", "link_source", "email_source", "email_status")} == {
        "contact_tried": TODAY.isoformat(),
        "link_source": "apollo",
        "email_source": "apollo",
        "email_status": "verified",
    }
    assert (bo.linkedin, bo.email, bo.details["contact_tried"]) == (None, None, TODAY.isoformat())
    assert (cy.linkedin, cy.email) == ("https://www.linkedin.com/in/cy-typed", None)  # the typed link stays
    assert db.scalar(select(Activity.text).where(Activity.company_id == c.id, Activity.kind == "research")) == (
        "Acme: Apollo found LinkedIn for 1 person and verified emails for 1 person"
    )

    again = signed_in.post("/api/people/contacts").json()
    assert again == {"tried": 0, "links": 0, "emails": 0, "left": 0}  # nobody is paid for twice
    assert len(apollo.requests) == 1


@pytest.mark.parametrize("blank", [" \t", "\u00a0"])  # a no-break space isn't whitespace to Postgres's \s in C
def test_a_blank_link_counts_as_none(db: Session, blank: str) -> None:
    c = f.company(db, name="Acme", domain=ACME)
    ana, _ = f.person(db, c, name="Ana Example")
    ana.linkedin = blank  # the import from the old tracker kept such values as they were
    db.flush()
    fake = FakeApollo({"Ana Example": hit("Ana", "Example")})
    assert contacts.fill_board(db, fake, TODAY, 10) == contacts.Filled(tried=1, links=1, emails=0, left=0)
    db.refresh(ana)
    assert ana.linkedin == link("Ana", "Example")


@pytest.mark.parametrize("stored", ["will@acme.example", "will@gmail.example", None])
def test_apollo_is_asked_by_name_and_company_only(db: Session, stored: str | None) -> None:
    c = f.company(db, name="Acme (Holdings)", domain=ACME)
    will, _ = f.person(db, c, name="William (Will) Example")
    will.email = stored  # never sent: it could be a personal address
    db.flush()
    fake = FakeApollo()
    contacts.fill_board(db, fake, TODAY, 10)
    assert fake.requests == [[{"name": "William Example", "organization_name": "Acme", "domain": ACME}]]


def test_ten_people_a_request_and_no_more_than_the_limit(db: Session) -> None:
    c = f.company(db, name="Acme", domain=ACME)
    for i in range(14):
        f.person(db, c, name=f"Ana Example{chr(97 + i)}")
    db.flush()
    fake = FakeApollo()
    assert contacts.fill_board(db, fake, TODAY, 12) == contacts.Filled(tried=12, links=0, emails=0, left=2)
    assert [len(r) for r in fake.requests] == [10, 2]


def test_a_link_or_email_typed_in_during_the_lookup_wins(db: Session) -> None:
    c = f.company(db, name="Acme", domain=ACME)
    ana, _ = f.person(db, c, name="Ana Example")
    db.flush()
    typed_link, typed_email = "https://www.linkedin.com/in/ana-typed-by-hand", "ana.typed@acme.example"

    class Slow(FakeApollo):
        def bulk_match(self, details: list[dict[str, Any]]) -> list[dict[str, Any] | None]:  # noqa: ARG002
            db.execute(
                update(Person).where(Person.id == ana.id).values(linkedin=typed_link, email=typed_email),
                execution_options={"synchronize_session": False},
            )
            return [hit("Ana", "Example", email_status="verified")]

    done = contacts.fill_board(db, Slow(), TODAY, 10)
    assert (done.links, done.emails) == (0, 0)
    db.refresh(ana)
    assert (ana.linkedin, ana.email, ana.details["contact_tried"]) == (typed_link, typed_email, TODAY.isoformat())
    assert "link_source" not in ana.details
    assert "email_source" not in ana.details


def test_when_apollo_fails_nobody_is_marked_tried(signed_in: TestClient, db: Session, apollo: FakeApollo) -> None:
    c = f.company(db, name="Acme", domain=ACME)
    ana, _ = f.person(db, c, name="Ana Example")
    db.flush()

    def down(details: list[dict[str, Any]]) -> list[dict[str, Any] | None]:
        raise ApolloError("Apollo 422: insufficient credits")

    apollo.bulk_match = down  # type: ignore[method-assign]
    assert signed_in.post("/api/people/contacts").json() == {"tried": 0, "links": 0, "emails": 0, "left": 1}
    db.refresh(ana)
    assert "contact_tried" not in ana.details


# ----------------------------------------------------------------------------- the Fractional list


def test_fractional_people_get_links_and_emails_that_outlast_the_research_sync(
    signed_in: TestClient, db: Session, apollo: FakeApollo
) -> None:
    people = [
        {"key": "ana", "name": "Ana Example", "title": "CEO"},
        {"key": "bo", "name": "Bo Example"},
        {"key": "cy", "name": "Cy Example", "linkedin": "https://www.linkedin.com/in/cy-from-research"},
    ]
    sync(signed_in, prospect("acme", people=people), prospect("gone", people=[{"key": "di", "name": "Di Example"}]))
    signed_in.patch("/api/fx/prospects/gone", json={"status": "lost"})  # closed: not worth a credit
    apollo.people = {
        "Ana Example": hit("Ana", "Example", domain="acme.example", org="Acme Example", email_status="verified")
    }

    # Cy has a link from research but no email, so Cy is asked too
    assert signed_in.post("/api/people/contacts").json() == {"tried": 3, "links": 1, "emails": 1, "left": 0}
    assert sorted(apollo.asked) == ["Ana Example", "Bo Example", "Cy Example"]
    assert apollo.requests[0][0]["organization_name"] == "Acme Example"

    def shown() -> dict[str, tuple[str | None, str | None]]:
        people = signed_in.get("/api/fx/prospects/acme").json()["people"]
        return {p["key"]: (p["linkedin"], p["email"]) for p in people}

    expected = {
        "ana": (link("Ana", "Example"), "ana@acme.example"),
        "bo": (None, None),
        "cy": ("https://www.linkedin.com/in/cy-from-research", None),
    }
    assert shown() == expected
    sync(signed_in, prospect("acme", people=people, why_now="Hiring a CRO"))  # the research is replaced
    assert shown() == expected
    assert signed_in.post("/api/people/contacts").json() == {"tried": 0, "links": 0, "emails": 0, "left": 0}
    assert db.scalar(select(Activity.text).where(Activity.text.like("%Apollo found%"))) == (
        "Acme Example: Apollo found LinkedIn for 1 person and verified emails for 1 person"
    )


def test_a_fractional_find_stays_with_the_person_and_company_it_was_found_for(
    signed_in: TestClient, db: Session, apollo: FakeApollo
) -> None:
    people = [
        {"key": "ana", "name": "Ana Example", "linkedin": "https://www.linkedin.com/in/ana-from-research"},
        {"key": "bo", "name": "Bo Example"},
    ]
    sync(signed_in, prospect("acme", people=people))
    apollo.people = {
        "Ana Example": hit("Ana", "Example", email_status="verified"),
        "Bo Example": hit("Bo", "Example", email_status="verified"),
    }
    assert signed_in.post("/api/people/contacts").json() == {"tried": 2, "links": 1, "emails": 2, "left": 0}

    def shown() -> dict[str, tuple[str | None, str | None]]:
        people = signed_in.get("/api/fx/prospects/acme").json()["people"]
        return {p["key"]: (p["linkedin"], p["email"]) for p in people}

    assert shown() == {
        "ana": ("https://www.linkedin.com/in/ana-from-research", "ana@acme.example"),
        "bo": (link("Bo", "Example"), "bo@acme.example"),
    }

    # the research gives Ana's key to someone else: Ana's email never shows on them, and they're asked about
    people[0] = {**people[0], "name": "Ann Other"}
    sync(signed_in, prospect("acme", people=people))
    assert shown()["ana"] == ("https://www.linkedin.com/in/ana-from-research", None)
    assert signed_in.post("/api/people/contacts").json() == {"tried": 1, "links": 0, "emails": 0, "left": 0}
    assert apollo.asked[-1] == "Ann Other"  # Apollo knows no Ann Other: Ana's finds are gone, not handed on
    assert shown()["ana"] == ("https://www.linkedin.com/in/ana-from-research", None)
    assert signed_in.post("/api/people/contacts").json() == {"tried": 0, "links": 0, "emails": 0, "left": 0}

    # the prospect moves to a new domain: the old finds stop showing until Apollo is asked at the new one
    sync(signed_in, prospect("acme", domain="acme-new.example", people=people))
    assert shown() == {"ana": ("https://www.linkedin.com/in/ana-from-research", None), "bo": (None, None)}
    apollo.people["Bo Example"] = hit("Bo", "Example", domain="acme-new.example", email_status="verified")
    assert signed_in.post("/api/people/contacts").json() == {"tried": 2, "links": 1, "emails": 1, "left": 0}
    assert shown()["bo"] == (link("Bo", "Example"), "bo@acme-new.example")


def test_finds_saved_without_whom_they_were_for_are_hidden_and_asked_again(
    signed_in: TestClient, db: Session, apollo: FakeApollo
) -> None:
    sync(signed_in, prospect("acme", people=[{"key": "ana", "name": "Ana Example"}]))
    row = db.get(Prospect, "acme")
    assert row is not None
    row.mine = {
        **row.mine,
        "links": {"ana": "https://www.linkedin.com/in/someone"},
        "emails": {"ana": "someone@acme.example"},
        "contact_tried": {"ana": TODAY.isoformat()},
    }
    db.flush()
    assert signed_in.get("/api/fx/prospects/acme").json()["people"][0]["email"] is None
    assert signed_in.post("/api/people/contacts").json() == {"tried": 1, "links": 0, "emails": 0, "left": 0}
    assert apollo.asked == ["Ana Example"]


def test_research_that_changes_during_the_lookup_keeps_the_find_off_the_new_person(
    signed_in: TestClient, db: Session
) -> None:
    sync(signed_in, prospect("acme", people=[{"key": "ana", "name": "Ana Example"}]))

    class Slow(FakeApollo):
        def bulk_match(self, details: list[dict[str, Any]]) -> list[dict[str, Any] | None]:  # noqa: ARG002
            db.execute(
                update(Prospect)
                .where(Prospect.id == "acme")
                .values(research={"people": [{"key": "ana", "name": "Ann Other"}]}),
                execution_options={"synchronize_session": False},
            )
            return [hit("Ana", "Example", email_status="verified")]

    assert contacts.fill_fractional(db, Slow(), TODAY, 10).emails == 1  # found for Ana, as asked
    row = db.get(Prospect, "acme")
    assert row is not None
    db.refresh(row)
    ann = fx_board.card(row, TODAY).people[0]
    assert (ann.name, ann.linkedin, ann.email) == ("Ann Other", None, None)
    assert contacts.fill_fractional(db, FakeApollo(), TODAY, 10).tried == 1  # Ann is asked about in turn


def test_the_board_goes_first_then_the_fractional_list(db: Session, signed_in: TestClient) -> None:
    sync(signed_in, prospect("acme", people=[{"key": "bo", "name": "Bo Example"}]))
    c = f.company(db, name="Acme", domain=ACME)
    f.person(db, c, name="Ana Example")
    db.flush()
    fake = FakeApollo()
    assert contacts.fill(db, fake, TODAY, 1) == contacts.Filled(tried=1, links=0, emails=0, left=1)
    assert fake.asked == ["Ana Example"]


def test_people_are_read_a_page_at_a_time_and_only_the_limit_is_kept(
    db: Session, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(contacts, "PAGE", 2)
    c = f.company(db, name="Acme", domain=ACME)
    for i in range(5):
        f.person(db, c, name=f"Ana Example{chr(97 + i)}")
    sync(signed_in, prospect("acme", people=[{"key": f"k{i}", "name": f"Bo Example{chr(97 + i)}"} for i in range(3)]))
    db.flush()
    fake = FakeApollo()
    assert contacts.fill(db, fake, TODAY, 0) == contacts.Filled(
        tried=0, links=0, emails=0, left=8
    )  # counted, nobody asked
    assert fake.requests == []
    assert contacts.fill(db, fake, TODAY, 6) == contacts.Filled(tried=6, links=0, emails=0, left=2)
    assert [len(r) for r in fake.requests] == [5, 1]
    assert contacts.fill(db, fake, TODAY, 6) == contacts.Filled(tried=2, links=0, emails=0, left=0)


# ----------------------------------------------------------------------------- the route and the client


def test_links_work_without_sign_in_but_need_apollo(client: TestClient) -> None:
    settings = get_settings()
    overrides = client.app.dependency_overrides  # type: ignore[attr-defined]
    overrides[get_settings] = lambda: settings.model_copy(update={"open_access": True, "apollo_api_key": None})
    r = client.post("/api/people/contacts")
    assert (r.status_code, r.json()["detail"]) == (409, "Apollo isn't set up (APOLLO_API_KEY).")
    key = SecretStr("made-up-key")
    overrides[get_settings] = lambda: settings.model_copy(update={"open_access": True, "apollo_api_key": key})
    assert client.post("/api/people/contacts").json() == {
        "tried": 0,
        "links": 0,
        "emails": 0,
        "left": 0,
    }  # nobody to ask: no call


def test_the_client_matches_ten_at_a_time_and_never_asks_for_personal_details() -> None:
    sent: list[httpx2.Request] = []

    def api(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200, json={"matches": [{"first_name": "Ana"}, None]})

    client = Apollo("test-key", transport=httpx2.MockTransport(api))
    asked = [{"name": "Ana Example"}, {"name": "Bo Example"}, {"name": "Cy Example"}]
    assert client.bulk_match(asked) == [{"first_name": "Ana"}, None, None]
    body = sent[0].read().decode().replace(" ", "")
    assert sent[0].url.path.endswith("/people/bulk_match")
    assert '"reveal_personal_emails":false' in body
    assert '"reveal_phone_number":false' in body
    assert sent[0].headers["X-Api-Key"] == "test-key"
    assert client.bulk_match([]) == []
    with pytest.raises(ValueError, match="at most 10"):
        client.bulk_match([{"name": f"Person {i}"} for i in range(11)])
    assert len(sent) == 1


# ----------------------------------------------------------------------------- the radar pass


@pytest.fixture
def factory(connection: Connection) -> sessionmaker[Session]:
    return sessionmaker(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)


def test_each_radar_pass_finds_links_for_new_people(db: Session, factory: sessionmaker[Session]) -> None:
    c = f.company(db, name="Acme", domain=ACME)
    ana, _ = f.person(db, c, name="Ana Example")
    db.commit()
    fake = FakeApollo({"Ana Example": hit("Ana", "Example")})
    radar.run_once(factory, get_settings(), radar.Tools(web=FakeWeb(), treg=None, apollo=fake), "test")
    db.refresh(ana)
    assert ana.linkedin == link("Ana", "Example")
    line = db.scalar(select(Activity.text).where(Activity.text.like("Job radar:%")))
    assert line is not None
    assert line.endswith("Apollo: 1 LinkedIn links and 0 verified emails")


def test_a_links_failure_never_fails_the_radar_pass(
    db: Session, factory: sessionmaker[Session], caplog: pytest.LogCaptureFixture
) -> None:
    c = f.company(db, name="Acme", domain=ACME)
    f.person(db, c, name="Ana Example")
    db.commit()

    class Broken(FakeApollo):
        def bulk_match(self, details: list[dict[str, Any]]) -> list[dict[str, Any] | None]:  # noqa: ARG002
            raise RuntimeError("something unexpected")

    caplog.set_level(logging.ERROR, logger="gtm_tracker.radar")
    radar.run_once(factory, get_settings(), radar.Tools(web=FakeWeb(), treg=None, apollo=Broken()), "test")
    # only the kind of error is logged: a database error's text would carry the values, such as LinkedIn links
    assert "finding LinkedIn links and emails failed: RuntimeError" in caplog.text
    assert "something unexpected" not in caplog.text
    with factory() as session:
        status = radar.get_setting(session, "radar_status", {})
    assert (status["error"], status["summary"]["links_found"]) == ("", 0)
