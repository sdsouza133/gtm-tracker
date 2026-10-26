from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.demo import COMPANIES, seed_demo
from app.models import Company, Move, Person, Setting


def test_seeds_an_empty_database_once(db: Session) -> None:
    assert seed_demo(db, today=date(2026, 10, 26)) == f"Added {len(COMPANIES)} demo companies."
    assert db.scalar(select(func.count()).select_from(Company)) == len(COMPANIES)
    people = sum(len(c.people) for c in COMPANIES)
    assert db.scalar(select(func.count()).select_from(Person)) == people
    assert db.scalar(select(func.count()).select_from(Move)) == people + len(COMPANIES)
    assert seed_demo(db) == "The database already has companies; nothing added."


def test_demo_data_is_fictional() -> None:
    assert all(c.domain.endswith(".example") for c in COMPANIES)


def test_seeding_keeps_a_candidate_name_already_set(db: Session) -> None:
    db.add(Setting(key="candidate", value="Someone Else"))
    db.flush()
    seed_demo(db, today=date(2026, 10, 26))
    assert db.get(Setting, "candidate").value == "Someone Else"  # type: ignore[union-attr]
