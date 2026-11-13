"""The rolling 15-day TTL: untouched companies are parked once their role (or, with no role, their entry) is too old."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import Connection
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import Activity, Company, MoveStatus, MoveType, ParkedWhy, Setting, Stage
from app.radar import run as radar
from tests import factories as f

TODAY = date(2026, 11, 13)


@pytest.fixture
def factory(connection: Connection) -> sessionmaker[Session]:
    return sessionmaker(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)


def added(db: Session, c: Company, days_ago: int) -> Company:
    c.created_at = datetime.combine(TODAY - timedelta(days=days_ago), datetime.min.time(), UTC)
    db.flush()
    return c


def test_untouched_companies_are_parked_after_15_days(db: Session) -> None:
    old_role = f.company(db, name="Old Role", posted=TODAY - timedelta(days=16))
    fresh_role = f.company(db, name="Fresh Role", posted=TODAY - timedelta(days=15))
    old_bench = added(db, f.company(db, name="Old Bench", stage=Stage.BENCH), 20)
    new_bench = added(db, f.company(db, name="New Bench", stage=Stage.BENCH), 3)
    relisted = f.company(db, name="Relisted", posted=TODAY - timedelta(days=40), research={"relisted": "2026-11-12"})

    parked = radar.park_untouched(db, TODAY, 15)

    assert parked == ["Old Bench (20d)", "Old Role (16d)"]
    assert (old_role.stage, old_role.parked_why) == (Stage.PARKED, ParkedWhy.STALE_ROLE)
    assert old_role.parked_reason is not None
    assert old_role.parked_reason.startswith("Role posted 2026-10-28 (16 days ago).")
    assert old_bench.stage is Stage.PARKED
    assert old_bench.parked_reason is not None
    assert "with no role" in old_bench.parked_reason
    assert fresh_role.stage is Stage.NOT_STARTED  # 15 days is still in
    assert new_bench.stage is Stage.BENCH
    assert relisted.stage is Stage.NOT_STARTED  # a re-listed role counts from its new date
    assert any("Parked 2 untouched companies" in a.text for a in db.query(Activity))


def test_companies_with_anything_done_are_never_parked(db: Session) -> None:
    worked = f.company(db, name="Worked", posted=TODAY - timedelta(days=30))
    f.move(db, worked, type=MoveType.APPLY, due=TODAY - timedelta(days=20), status=MoveStatus.DONE)
    talking = f.company(db, name="Talking", stage=Stage.CONTACTED, posted=TODAY - timedelta(days=30))
    replied = f.company(db, name="Replied", stage=Stage.REPLIED, posted=TODAY - timedelta(days=60))
    by_hand = f.company(db, name="By Hand", stage=Stage.PARKED, parked_why=ParkedWhy.MANUAL, posted=TODAY)

    assert radar.park_untouched(db, TODAY, 15) == []
    assert (worked.stage, talking.stage, replied.stage) == (Stage.NOT_STARTED, Stage.CONTACTED, Stage.REPLIED)
    assert by_hand.stage is Stage.PARKED  # parked on purpose: a fresh role doesn't bring it back


def test_a_company_parked_for_its_age_comes_back_when_its_role_is_fresh_again(db: Session) -> None:
    back = f.company(
        db, name="Back", stage=Stage.PARKED, parked_why=ParkedWhy.STALE_ROLE, posted=TODAY - timedelta(days=2)
    )
    still_old = f.company(
        db, name="Still Old", stage=Stage.PARKED, parked_why=ParkedWhy.STALE_ROLE, posted=TODAY - timedelta(days=30)
    )
    no_role = added(db, f.company(db, name="No Role", stage=Stage.PARKED, parked_why=ParkedWhy.STALE_ROLE), 30)

    radar.park_untouched(db, TODAY, 15)

    assert (back.stage, back.parked_why) == (Stage.NOT_STARTED, None)
    assert (still_old.stage, no_role.stage) == (Stage.PARKED, Stage.PARKED)


def test_the_ttl_follows_the_radar_setting(db: Session) -> None:
    c = f.company(db, name="Ten Days", posted=TODAY - timedelta(days=10))
    assert radar.park_untouched(db, TODAY, 15) == []
    assert radar.park_untouched(db, TODAY, 7) == ["Ten Days (10d)"]
    assert c.stage is Stage.PARKED


def test_the_daily_check_runs_once_a_day(db: Session, factory: sessionmaker[Session]) -> None:
    settings = get_settings()
    today = datetime.now(settings.tz).date()
    old = f.company(db, name="Old Role", posted=today - timedelta(days=40))
    db.commit()

    assert radar.expire_untouched(factory, settings) == ["Old Role (40d)"]
    db.refresh(old)
    assert old.stage is Stage.PARKED
    ran = db.get(Setting, radar.TTL_LAST_RUN)
    assert ran is not None
    assert ran.value == today.isoformat()  # the scheduler skips the rest of the day
