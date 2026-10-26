"""Small builders for test data. Everything here is made up."""

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.models import Company, Move, MoveType, Person, RoleInHire, Stage, Sureness, new_id
from app.services import outreach


def company(db: Session, *, stage: Stage = Stage.NOT_STARTED, **kw: Any) -> Company:
    c = Company(id=kw.pop("id", new_id("c")), name=kw.pop("name", "Acme Example"), stage=stage, **kw)
    db.add(c)
    db.flush()
    return c


def person(
    db: Session,
    at: Company,
    *,
    name: str = "Pat Example",
    day0: date | None = None,
    role: RoleInHire = RoleInHire.HIRING_MANAGER,
    sure: Sureness | None = Sureness.LIKELY,
) -> tuple[Person, Move | None]:
    p = Person(company=at, name=name, role_in_hire=role, sureness=sure, title="VP Sales")
    db.add(p)
    db.flush()
    move = outreach.start_reach(db, p, day0) if day0 else None
    db.flush()
    return p, move


def move(db: Session, at: Company | None, *, type: MoveType, due: date, **kw: Any) -> Move:
    m = Move(company=at, type=type, title=kw.pop("title", f"{type.value} move"), due=due, **kw)
    db.add(m)
    db.flush()
    return m
