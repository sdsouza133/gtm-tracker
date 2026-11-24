"""LinkedIn profile links from Apollo, with a fake Apollo. Every name, company and link here is made up."""

import logging
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Connection, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.api.enrich import get_link_finder
from app.config import get_settings
from app.enrich.apollo import Apollo, ApolloError
from app.models import Activity, Person
from app.radar import run as radar
from app.services import links
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
    signed_in.app.dependency_overrides[get_link_finder] = lambda: fake  # type: ignore[attr-defined]
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
    assert links.verified_link(name, company, domain, found) == expected


def test_links_come_back_in_one_shape() -> None:
    assert (
        links.profile_link("http://linkedin.com/in/ana-example?trk=feed") == "https://www.linkedin.com/in/ana-example"
    )
    assert links.profile_link("https://ca.linkedin.com/in/ana-example/") == "https://www.linkedin.com/in/ana-example"
    assert links.profile_link("https://example.com/in/ana") is None


# ----------------------------------------------------------------------------- the board


def test_people_on_the_board_get_their_link_once_and_nothing_else(
    signed_in: TestClient, db: Session, apollo: FakeApollo
) -> None:
    c = f.company(db, name="Acme", domain=ACME)
    ana, _ = f.person(db, c, name="Ana Example")
    bo, _ = f.person(db, c, name="Bo Example")
    linked, _ = f.person(db, c, name="Cy Example")
    linked.linkedin = "https://www.linkedin.com/in/cy-typed"
    gone, _ = f.person(db, c, name="Di Example")
    gone.left = True
    f.person(db, c, name="Ed")  # a first name alone isn't asked about
    elsewhere = f.company(db, name="No Site")
    f.person(db, elsewhere, name="Fay Example")  # no domain: nothing to check the company against
    db.flush()
    apollo.people = {"Ana Example": hit("Ana", "Example"), "Bo Example": hit("Bo", "Stranger")}

    assert signed_in.post("/api/people/links").json() == {"tried": 2, "found": 1, "left": 0}
    assert sorted(apollo.asked) == ["Ana Example", "Bo Example"]
    db.refresh(ana)
    db.refresh(bo)
    assert (ana.linkedin, ana.email) == (link("Ana", "Example"), None)  # never the email Apollo sent
    assert (ana.details["link_tried"], ana.details["link_source"]) == (TODAY.isoformat(), "apollo")
    assert (bo.linkedin, bo.details["link_tried"]) == (None, TODAY.isoformat())
    assert db.scalar(select(Activity.text).where(Activity.company_id == c.id, Activity.kind == "research")) == (
        "Acme: Apollo found LinkedIn for 1 person"
    )

    assert signed_in.post("/api/people/links").json() == {"tried": 0, "found": 0, "left": 0}  # a miss isn't paid twice
    assert len(apollo.requests) == 1


def test_a_blank_link_counts_as_none(db: Session) -> None:
    c = f.company(db, name="Acme", domain=ACME)
    ana, _ = f.person(db, c, name="Ana Example")
    ana.linkedin = " \t"  # the import from the old tracker kept such values as they were
    db.flush()
    fake = FakeApollo({"Ana Example": hit("Ana", "Example")})
    assert links.fill_board(db, fake, TODAY, 10) == links.Filled(tried=1, found=1, left=0)
    db.refresh(ana)
    assert ana.linkedin == link("Ana", "Example")


def test_a_work_email_we_have_helps_apollo_find_them(db: Session) -> None:
    c = f.company(db, name="Acme (Holdings)", domain=ACME)
    ana, _ = f.person(db, c, name="William (Will) Example")
    ana.email = "will@acme.example"
    db.flush()
    fake = FakeApollo()
    links.fill_board(db, fake, TODAY, 10)
    assert fake.requests == [
        [{"name": "William Example", "organization_name": "Acme", "domain": ACME, "email": "will@acme.example"}]
    ]


def test_ten_people_a_request_and_no_more_than_the_limit(db: Session) -> None:
    c = f.company(db, name="Acme", domain=ACME)
    for i in range(14):
        f.person(db, c, name=f"Ana Example{chr(97 + i)}")
    db.flush()
    fake = FakeApollo()
    assert links.fill_board(db, fake, TODAY, 12) == links.Filled(tried=12, found=0, left=2)
    assert [len(r) for r in fake.requests] == [10, 2]


def test_a_link_typed_in_during_the_lookup_wins(db: Session) -> None:
    c = f.company(db, name="Acme", domain=ACME)
    ana, _ = f.person(db, c, name="Ana Example")
    db.flush()
    typed = "https://www.linkedin.com/in/ana-typed-by-hand"

    class Slow(FakeApollo):
        def bulk_match(self, details: list[dict[str, Any]]) -> list[dict[str, Any] | None]:  # noqa: ARG002
            db.execute(
                update(Person).where(Person.id == ana.id).values(linkedin=typed),
                execution_options={"synchronize_session": False},
            )
            return [hit("Ana", "Example")]

    assert links.fill_board(db, Slow(), TODAY, 10).found == 0
    db.refresh(ana)
    assert (ana.linkedin, ana.details["link_tried"], "link_source" in ana.details) == (typed, TODAY.isoformat(), False)


def test_when_apollo_fails_nobody_is_marked_tried(signed_in: TestClient, db: Session, apollo: FakeApollo) -> None:
    c = f.company(db, name="Acme", domain=ACME)
    ana, _ = f.person(db, c, name="Ana Example")
    db.flush()

    def down(details: list[dict[str, Any]]) -> list[dict[str, Any] | None]:
        raise ApolloError("Apollo 422: insufficient credits")

    apollo.bulk_match = down  # type: ignore[method-assign]
    assert signed_in.post("/api/people/links").json() == {"tried": 0, "found": 0, "left": 1}
    db.refresh(ana)
    assert "link_tried" not in ana.details


# ----------------------------------------------------------------------------- the Fractional list


def test_fractional_people_get_links_that_outlast_the_research_sync(
    signed_in: TestClient, db: Session, apollo: FakeApollo
) -> None:
    people = [
        {"key": "ana", "name": "Ana Example", "title": "CEO"},
        {"key": "bo", "name": "Bo Example"},
        {"key": "cy", "name": "Cy Example", "linkedin": "https://www.linkedin.com/in/cy-from-research"},
    ]
    sync(signed_in, prospect("acme", people=people), prospect("gone", people=[{"key": "di", "name": "Di Example"}]))
    signed_in.patch("/api/fx/prospects/gone", json={"status": "lost"})  # closed: not worth a credit
    apollo.people = {"Ana Example": hit("Ana", "Example", domain="acme.example", org="Acme Example")}

    assert signed_in.post("/api/people/links").json() == {"tried": 2, "found": 1, "left": 0}
    assert sorted(apollo.asked) == ["Ana Example", "Bo Example"]
    assert apollo.requests[0][0]["organization_name"] == "Acme Example"

    def shown() -> dict[str, str | None]:
        return {p["key"]: p["linkedin"] for p in signed_in.get("/api/fx/prospects/acme").json()["people"]}

    expected = {"ana": link("Ana", "Example"), "bo": None, "cy": "https://www.linkedin.com/in/cy-from-research"}
    assert shown() == expected
    sync(signed_in, prospect("acme", people=people, why_now="Hiring a CRO"))  # the research is replaced
    assert shown() == expected
    assert signed_in.post("/api/people/links").json() == {"tried": 0, "found": 0, "left": 0}
    assert db.scalar(select(Activity.text).where(Activity.text.like("%Apollo found LinkedIn%"))) == (
        "Acme Example: Apollo found LinkedIn for 1 person"
    )


def test_the_board_goes_first_then_the_fractional_list(db: Session, signed_in: TestClient) -> None:
    sync(signed_in, prospect("acme", people=[{"key": "bo", "name": "Bo Example"}]))
    c = f.company(db, name="Acme", domain=ACME)
    f.person(db, c, name="Ana Example")
    db.flush()
    fake = FakeApollo()
    assert links.fill(db, fake, TODAY, 1) == links.Filled(tried=1, found=0, left=1)
    assert fake.asked == ["Ana Example"]


def test_people_are_read_a_page_at_a_time_and_only_the_limit_is_kept(
    db: Session, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(links, "PAGE", 2)
    c = f.company(db, name="Acme", domain=ACME)
    for i in range(5):
        f.person(db, c, name=f"Ana Example{chr(97 + i)}")
    sync(signed_in, prospect("acme", people=[{"key": f"k{i}", "name": f"Bo Example{chr(97 + i)}"} for i in range(3)]))
    db.flush()
    fake = FakeApollo()
    assert links.fill(db, fake, TODAY, 0) == links.Filled(tried=0, found=0, left=8)  # counted, nobody asked
    assert fake.requests == []
    assert links.fill(db, fake, TODAY, 6) == links.Filled(tried=6, found=0, left=2)
    assert [len(r) for r in fake.requests] == [5, 1]
    assert links.fill(db, fake, TODAY, 6) == links.Filled(tried=2, found=0, left=0)


# ----------------------------------------------------------------------------- the route and the client


def test_links_work_without_sign_in_but_need_apollo(client: TestClient) -> None:
    settings = get_settings()
    overrides = client.app.dependency_overrides  # type: ignore[attr-defined]
    overrides[get_settings] = lambda: settings.model_copy(update={"open_access": True, "apollo_api_key": None})
    r = client.post("/api/people/links")
    assert (r.status_code, r.json()["detail"]) == (409, "Apollo isn't set up (APOLLO_API_KEY).")
    key = SecretStr("made-up-key")
    overrides[get_settings] = lambda: settings.model_copy(update={"open_access": True, "apollo_api_key": key})
    assert client.post("/api/people/links").json() == {"tried": 0, "found": 0, "left": 0}  # nobody to ask: no call


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
    assert line.endswith("LinkedIn links found for 1 person")


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
    assert "finding LinkedIn links failed: RuntimeError" in caplog.text
    assert "something unexpected" not in caplog.text
    with factory() as session:
        status = radar.get_setting(session, "radar_status", {})
    assert (status["error"], status["summary"]["links_found"]) == ("", 0)
