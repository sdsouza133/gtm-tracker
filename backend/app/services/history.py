"""Writing to the history. Each line says what happened in plain words; wins carry their XP."""

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models import Activity


def record(
    session: Session,
    kind: str,
    text: str,
    *,
    company_id: str | None = None,
    person_id: str | None = None,
    move_id: str | None = None,
    xp: int = 0,
    tag: str | None = None,
) -> Activity:
    row = Activity(kind=kind, text=text, company_id=company_id, person_id=person_id, move_id=move_id, xp=xp, tag=tag)
    session.add(row)
    return row


def already_won(session: Session, company_id: str, tag: str) -> bool:
    return bool(session.scalar(select(exists().where(Activity.company_id == company_id, Activity.tag == tag))))
