"""A full radar pass against the database, with the network and treg faked."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Connection, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import (
    Activity,
    Company,
    Move,
    MoveStatus,
    MoveType,
    ParkedWhy,
    Person,
    RadarItem,
    RoleInHire,
    Setting,
    Stage,
    Sureness,
)
from app.radar import people
from app.radar import run as radar
from app.radar.fit import RadarConfig
from app.radar.sources import JOB_DETAILS, LINKEDIN_JOBS, POST_SEARCH
from tests import factories as f
from tests.radar_fakes import FakeWeb, ashby, ashby_job, job_details, linkedin_item
from tests.treg_fakes import FakeTreg, pages

UUID_OLD = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
UUID_NEW = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
BOARD = {"ats": "ashby", "slug": "acme", "found_via": "careers page"}


@pytest.fixture
def factory(connection: Connection) -> sessionmaker[Session]:
    return sessionmaker(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)


@pytest.fixture
def today() -> date:
    return datetime.now(get_settings().tz).date()


def tracked(db: Session, today: date, **kw: Any) -> Company:
    old = {
        "title": "GTM Engineer",
        "url": f"https://jobs.ashbyhq.com/acme/{UUID_OLD}",
        "fit": 3,
        "posted": today.isoformat(),
    }
    return f.company(
        db,
        name="Acme",
        domain="acme.example",
        research={
            "jobs": {"board": BOARD, "postings": [old], "seen": [old["url"]], "checked_at": "2026-10-01T00:00:00+00:00"}
        },
        **kw,
    )


def test_a_new_board_posting_becomes_an_apply_move(db: Session, factory: sessionmaker[Session], today: date) -> None:
    c = tracked(db, today)
    linkedin = {"title": "GTM Engineer", "url": "https://www.linkedin.com/jobs/view/123", "fit": 3, "posted": ""}
    jobs = c.research["jobs"]
    c.research = {**c.research, "jobs": {**jobs, "postings": [*jobs["postings"], linkedin]}}  # added from the radar
    f.move(
        db,
        c,
        type=MoveType.APPLY,
        due=today,
        title="Apply: GTM Engineer",
        url=f"https://jobs.ashbyhq.com/acme/{UUID_OLD}",
    )
    db.commit()
    web = FakeWeb(json_by_url=ashby("acme", ashby_job("Senior GTM Engineer", UUID_NEW, posted=today.isoformat())))
    assert radar.run_once(factory, get_settings(), radar.Tools(web=web, treg=None), "test")

    moves = db.scalars(select(Move).where(Move.company_id == c.id).order_by(Move.created_at)).all()
    assert [m.title for m in moves] == ["Apply: GTM Engineer"]  # one open Apply move per company
    assert "was gone from their job board" in moves[0].notes  # the old posting closed
    db.refresh(c)
    assert [p["title"] for p in c.research["jobs"]["postings"]] == ["Senior GTM Engineer"]
    status = db.get(Setting, "radar_status")
    assert status is not None
    assert (status.value["running"], status.value["summary"]["tracked_new"], status.value["summary"]["closed"]) == (
        False,
        1,
        1,  # the LinkedIn posting was never on the board, so it didn't close
    )
    assert status.value["last_run_date"] == today.isoformat()
    lines = db.scalars(select(Activity.text).where(Activity.kind == "radar")).all()
    assert any("new role on their job board: Senior GTM Engineer" in line for line in lines)


def test_a_parked_company_comes_back_when_it_posts_again(
    db: Session, factory: sessionmaker[Session], today: date
) -> None:
    c = tracked(db, today, stage=Stage.PARKED, parked_why=ParkedWhy.STALE_ROLE)
    db.commit()
    web = FakeWeb(json_by_url=ashby("acme", ashby_job("GTM Engineer", UUID_NEW, posted=today.isoformat())))
    radar.run_once(factory, get_settings(), radar.Tools(web=web, treg=None), "test")
    db.refresh(c)
    assert (c.stage, c.parked_why) == (Stage.NOT_STARTED, None)
    apply = db.scalars(select(Move).where(Move.company_id == c.id, Move.type == MoveType.APPLY)).one()
    assert apply.due == today


def test_linkedin_roles_go_to_tracked_companies_or_the_inbox(
    db: Session, factory: sessionmaker[Session], today: date
) -> None:
    beta = f.company(db, name="Beta Labs", stage=Stage.NOT_STARTED)
    bench = f.company(db, name="Gamma", stage=Stage.BENCH)
    db.commit()
    treg = FakeTreg(
        {
            LINKEDIN_JOBS: pages(
                [
                    linkedin_item("1", "GTM Engineer", "Beta Labs"),
                    linkedin_item("2", "GTM Engineer", "Delta"),
                    linkedin_item("3", "GTM Engineer", "Gamma"),
                    linkedin_item("4", "GTM Engineer", "TalentCo Staffing"),
                    linkedin_item("5", "Account Executive", "Epsilon"),
                ],
                25,
            ),
            JOB_DETAILS: job_details(),
            POST_SEARCH: {
                "elements": [
                    {
                        "id": "p1",
                        "content": "We're hiring a GTM engineer! DM me.",
                        "author": {"name": "Pat"},
                        "postedAt": {"date": "2026-10-25"},
                    },
                    {"id": "p2", "content": "Open to work as a GTM engineer", "author": {"name": "Sam"}},
                ]
            },
        }
    )
    tools = radar.Tools(web=FakeWeb(), treg=treg)
    radar.run_once(factory, get_settings(), tools, "test")
    assert db.scalars(select(Move.title).where(Move.company_id == beta.id)).all() == ["Apply: GTM Engineer"]
    inbox = {i.company: i for i in db.scalars(select(RadarItem))}
    assert set(inbox) == {"Delta", "Gamma"}  # no agencies, no off-target titles
    assert (inbox["Gamma"].company_id, inbox["Gamma"].data["on_bench"]) == (bench.id, True)
    posts = db.get(Setting, "radar_posts")
    assert posts is not None
    assert [p["id"] for p in posts.value] == ["p1"]

    radar.run_once(factory, get_settings(), tools, "test")  # a second pass adds nothing twice
    assert db.scalars(select(Move).where(Move.company_id == beta.id)).all().__len__() == 1
    assert len(db.scalars(select(RadarItem)).all()) == 2
    caps = {tool: cap for tool, _, _, cap in treg.calls}
    assert caps[LINKEDIN_JOBS] == pytest.approx(0.001)  # every call capped at its list price


def test_stale_roles_are_parked_and_errors_are_reported(
    db: Session, factory: sessionmaker[Session], today: date
) -> None:
    old = f.company(db, name="Old Role", posted=today - timedelta(days=20))
    fresh = f.company(db, name="Fresh Role", posted=today - timedelta(days=2))
    db.commit()
    treg = FakeTreg(fail={LINKEDIN_JOBS})
    radar.run_once(factory, get_settings(), radar.Tools(web=FakeWeb(), treg=treg), "test")
    db.refresh(old)
    db.refresh(fresh)
    assert (old.stage, old.parked_why) == (Stage.PARKED, ParkedWhy.STALE_ROLE)
    assert fresh.stage is Stage.NOT_STARTED
    status = db.get(Setting, "radar_status")
    assert status is not None
    assert "LinkedIn search failed" in status.value["error"]
    assert "last_linkedin_at" not in status.value  # the window stays open until a good run


def test_a_post_search_that_stopped_early_keeps_its_window_open(db: Session, factory: sessionmaker[Session]) -> None:
    treg = FakeTreg({LINKEDIN_JOBS: {"elements": []}}, fail={POST_SEARCH})
    radar.run_once(factory, get_settings(), radar.Tools(web=FakeWeb(), treg=treg), "test")
    status = db.get(Setting, "radar_status")
    assert status is not None
    assert "Hiring-post search failed" in status.value["error"]
    assert "last_posts_at" not in status.value  # searched again, over the same days, on the next run
    assert "last_linkedin_at" not in status.value


def test_strong_new_roles_go_on_the_board_with_people_to_write_to(
    db: Session, factory: sessionmaker[Session], today: date
) -> None:
    bench = f.company(db, name="Gamma", stage=Stage.BENCH)
    db.commit()
    leads = {
        "GTM": [
            {
                "name": "Val Example",
                "position": "Head of Revenue Operations at Delta",
                "linkedinUrl": "https://www.linkedin.com/in/val-example",
            }
        ],
        "revenue operations": [],
        "growth": [
            {
                "name": "Orla Example",
                "position": "Growth Consultant at Orama",
                "linkedinUrl": "https://www.linkedin.com/in/orla-example",
            }
        ],
    }
    treg = FakeTreg(
        {
            LINKEDIN_JOBS: pages(
                [
                    linkedin_item("21", "GTM Engineer", "Delta"),
                    linkedin_item("22", "GTM Engineer", "Gamma"),
                ],
                25,
            ),
            JOB_DETAILS: job_details(**{"21": {"company": {"employeeCount": 120}}}),
            people.PROFILE_SEARCH: lambda q, _b: {"elements": leads[q["title"]]},
        },
        prices={people.PROFILE_SEARCH: 0.002},
    )
    radar.run_once(factory, get_settings(), radar.Tools(web=FakeWeb(), treg=treg), "test")

    delta = db.scalars(select(Company).where(Company.name == "Delta")).one()
    assert (delta.stage, delta.employees, delta.linkedin) == (
        Stage.NOT_STARTED,
        "120",
        "https://www.linkedin.com/company/delta",
    )
    moves = db.scalars(select(Move).where(Move.company_id == delta.id).order_by(Move.title)).all()
    assert [m.type for m in moves if m.status is MoveStatus.OPEN] == [MoveType.APPLY, MoveType.REACH]
    assert "Found by a refresh" in next(m.notes for m in moves if m.type is MoveType.APPLY)
    found = db.scalars(select(Person).where(Person.company_id == delta.id)).all()
    assert [(p.name, p.role_in_hire, p.sureness) for p in found] == [
        ("Val Example", RoleInHire.HIRING_MANAGER, Sureness.LIKELY)  # the consultant is left out
    ]
    inbox = {i.company: i.state for i in db.scalars(select(RadarItem))}
    assert inbox == {"Delta": "added", "Gamma": "new"}  # a benched company's role waits for you
    assert db.scalars(select(Company).where(Company.name == "Gamma")).one().stage is Stage.BENCH
    status = db.get(Setting, "radar_status")
    assert status is not None
    summary = status.value["summary"]
    assert (summary["auto_added"], summary["people_added"]) == (1, 1)
    assert summary["people_usd"] == pytest.approx(0.006)
    lines = db.scalars(select(Activity.text).where(Activity.kind == "radar")).all()
    assert any("1 added to the board with 1 people to write to" in line for line in lines)
    assert bench.id


def test_two_postings_of_one_role_get_one_apply_move(db: Session, factory: sessionmaker[Session]) -> None:
    db.commit()
    treg = FakeTreg(
        {
            LINKEDIN_JOBS: pages(
                [linkedin_item("31", "GTM Engineer", "Delta"), linkedin_item("32", "GTM Engineer", "Delta")], 25
            ),
            JOB_DETAILS: job_details(),
        }
    )
    radar.run_once(factory, get_settings(), radar.Tools(web=FakeWeb(), treg=treg), "test")
    delta = db.scalars(select(Company).where(Company.name == "Delta")).one()
    applies = db.scalars(select(Move).where(Move.company_id == delta.id, Move.type == MoveType.APPLY)).all()
    assert len(applies) == 1
    assert [i.state for i in db.scalars(select(RadarItem))] == ["added", "added"]


def test_a_refresh_leaves_a_company_you_benched_since_the_role_was_found(
    db: Session, factory: sessionmaker[Session], today: date
) -> None:
    gamma = f.company(db, name="Gamma", stage=Stage.BENCH)
    since = datetime.now(UTC).isoformat()
    db.add(
        RadarItem(
            id="li-41",
            company="Gamma",
            title="GTM Engineer",
            url="https://www.linkedin.com/jobs/view/41",
            fit=3,
            state="new",
            data={"found_at": datetime.now(UTC).isoformat(), "on_bench": False},  # not benched when it was found
        )
    )
    db.commit()
    out = radar.auto_add(factory, RadarConfig(), radar.Tools(web=FakeWeb(), treg=None), today, since)
    db.refresh(gamma)
    assert (out["auto_added"], gamma.stage) == (0, Stage.BENCH)
    assert db.get(RadarItem, "li-41").state == "new"  # type: ignore[union-attr]


def test_with_auto_add_off_every_new_role_waits_in_the_inbox(db: Session, factory: sessionmaker[Session]) -> None:
    db.add(Setting(key="radar_config", value={"auto_add": False}))
    db.commit()
    treg = FakeTreg(
        {LINKEDIN_JOBS: pages([linkedin_item("21", "GTM Engineer", "Delta")], 25), JOB_DETAILS: job_details()}
    )
    radar.run_once(factory, get_settings(), radar.Tools(web=FakeWeb(), treg=treg), "test")
    assert db.scalars(select(Company).where(Company.name == "Delta")).first() is None
    assert [i.state for i in db.scalars(select(RadarItem))] == ["new"]
    assert people.PROFILE_SEARCH not in treg.tools()


def test_only_one_pass_at_a_time(db: Session, factory: sessionmaker[Session], connection: Connection) -> None:
    connection.execute(text("SELECT pg_advisory_lock(:k)"), {"k": radar.LOCK_KEY})
    try:
        other = sessionmaker(bind=connection.engine)  # a separate connection, like a second copy of the app
        assert radar.run_once(other, get_settings(), radar.Tools(web=FakeWeb(), treg=None), "test") is False
    finally:
        connection.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": radar.LOCK_KEY})
    assert db.get(Setting, "radar_status") is None


def test_the_lock_stays_on_one_connection_for_the_whole_pass(connection: Connection) -> None:
    engine = connection.engine
    factory = sessionmaker(bind=engine)

    def held() -> bool:  # asked from a connection of its own
        with engine.connect() as c:
            return bool(
                c.scalar(
                    text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND objid = :k AND granted"),
                    {"k": radar.LOCK_KEY},
                )
            )

    with radar.pass_lock(factory) as got:
        assert got
        for _ in range(3):  # the pass's sessions check connections out of the pool and back in
            with factory() as s:
                s.execute(text("SELECT 1"))
                s.commit()
        assert held()
        with radar.pass_lock(factory) as again:
            assert again is False
    assert not held()


def test_due_after_the_hour_once_a_day(db: Session) -> None:
    settings = get_settings()
    db.add(Setting(key="radar_config", value={"hour": 0}))
    db.flush()
    assert radar.due(db, settings)
    db.add(Setting(key="radar_status", value={"last_run_date": datetime.now(settings.tz).date().isoformat()}))
    db.flush()
    assert not radar.due(db, settings)


def test_a_bad_posted_date_is_dropped_not_fatal() -> None:
    assert radar._day("2026-10-25T10:00:00Z") == date(2026, 10, 25)
    assert radar._day("yesterday") is None
    assert radar._day(None) is None
