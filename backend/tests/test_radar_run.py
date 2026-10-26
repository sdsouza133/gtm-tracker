"""A full radar pass against the database, with the network and Apify faked."""

from datetime import date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Connection, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import Activity, Company, Move, MoveType, ParkedWhy, RadarItem, Setting, Stage
from app.radar import run as radar
from app.radar.sources import LINKEDIN_JOBS, POST_SEARCH
from tests import factories as f
from tests.radar_fakes import FakeApify, FakeWeb, ashby, ashby_job, linkedin_item

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
    assert radar.run_once(factory, get_settings(), radar.Tools(web=web, apify=None), "test")

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
        1,
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
    radar.run_once(factory, get_settings(), radar.Tools(web=web, apify=None), "test")
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
    apify = FakeApify(
        {
            LINKEDIN_JOBS: [
                linkedin_item("1", "GTM Engineer", "Beta Labs"),
                linkedin_item("2", "GTM Engineer", "Delta"),
                linkedin_item("3", "GTM Engineer", "Gamma"),
                linkedin_item("4", "GTM Engineer", "TalentCo Staffing"),
                linkedin_item("5", "Account Executive", "Epsilon"),
            ],
            POST_SEARCH: [
                {
                    "id": "p1",
                    "content": "We're hiring a GTM engineer! DM me.",
                    "author": {"name": "Pat"},
                    "postedAt": {"date": "2026-10-25"},
                },
                {"id": "p2", "content": "Open to work as a GTM engineer", "author": {"name": "Sam"}},
            ],
        }
    )
    tools = radar.Tools(web=FakeWeb(), apify=apify)
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
    caps = {actor: cap for actor, _, cap in apify.runs}
    assert caps[LINKEDIN_JOBS] == pytest.approx(0.30)


def test_stale_roles_are_parked_and_errors_are_reported(
    db: Session, factory: sessionmaker[Session], today: date
) -> None:
    old = f.company(db, name="Old Role", posted=today - timedelta(days=20))
    fresh = f.company(db, name="Fresh Role", posted=today - timedelta(days=2))
    db.commit()
    apify = FakeApify(fail={LINKEDIN_JOBS})
    radar.run_once(factory, get_settings(), radar.Tools(web=FakeWeb(), apify=apify), "test")
    db.refresh(old)
    db.refresh(fresh)
    assert (old.stage, old.parked_why) == (Stage.PARKED, ParkedWhy.STALE_ROLE)
    assert fresh.stage is Stage.NOT_STARTED
    status = db.get(Setting, "radar_status")
    assert status is not None
    assert "LinkedIn search failed" in status.value["error"]
    assert "last_linkedin_at" not in status.value  # the window stays open until a good run


def test_only_one_pass_at_a_time(db: Session, factory: sessionmaker[Session], connection: Connection) -> None:
    connection.execute(text("SELECT pg_advisory_lock(:k)"), {"k": radar.LOCK_KEY})
    try:
        other = sessionmaker(bind=connection.engine)  # a separate connection, like a second copy of the app
        assert radar.run_once(other, get_settings(), radar.Tools(web=FakeWeb(), apify=None), "test") is False
    finally:
        connection.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": radar.LOCK_KEY})
    assert db.get(Setting, "radar_status") is None


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
