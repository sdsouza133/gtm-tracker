"""People around each hire: adding them, changing them, logging a reply."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth import DbSession, SignedIn
from app.clock import Today
from app.models import Person, PersonStatus, RoleInHire, Sureness
from app.schemas import Page, PersonCreate, PersonOut, PersonPatch, Reply
from app.services.history import record
from app.services.outreach import NewPerson, add_person, mark_left, record_reply

router = APIRouter(prefix="/api/people", tags=["people"], dependencies=[SignedIn])


def get_person(session: Session, person_id: str) -> Person:
    person = session.get(Person, person_id)
    if person is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That person isn't in the tracker.")
    return person


@router.get("")
def list_people(
    session: DbSession,
    q: Annotated[str | None, Query(max_length=100)] = None,
    company_id: Annotated[str | None, Query(max_length=40)] = None,
    person_status: Annotated[PersonStatus | None, Query(alias="status")] = None,
    role: Annotated[RoleInHire | None, Query()] = None,
    sureness: Annotated[Sureness | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[PersonOut]:
    query = select(Person)
    if q:
        like = f"%{q.strip().replace('%', r'\%').replace('_', r'\_')}%"
        query = query.where(or_(Person.name.ilike(like), Person.title.ilike(like)))
    if company_id:
        query = query.where(Person.company_id == company_id)
    if person_status:
        query = query.where(Person.status == person_status)
    if role:
        query = query.where(Person.role_in_hire == role)
    if sureness:
        query = query.where(Person.sureness == sureness)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(query.order_by(Person.name, Person.id).limit(limit).offset(offset)).all()
    return Page(items=[PersonOut.model_validate(p) for p in rows], total=total)


@router.post("", status_code=status.HTTP_201_CREATED)
def create(body: PersonCreate, session: DbSession, today: Today) -> PersonOut:
    """Add someone at a company. They get a reach-out of their own."""
    person = add_person(session, NewPerson(**body.model_dump()), today)
    session.commit()
    return PersonOut.model_validate(person)


@router.patch("/{person_id}")
def update(person_id: str, body: PersonPatch, session: DbSession, today: Today) -> PersonOut:
    person = get_person(session, person_id)
    fields = body.model_dump(exclude_unset=True)
    new_status = fields.pop("status", None)
    left = fields.pop("left", None)
    for key, value in fields.items():
        setattr(person, key, value)
    if left is True and not person.left:
        mark_left(session, person, today)
    elif left is False:
        person.left = False
    if new_status is not None and new_status != person.status:
        if new_status is PersonStatus.REPLIED:
            record_reply(session, person, "", today)
        else:
            person.status = new_status
            record(
                session,
                "contact",
                f"{person.name}: {new_status.value.replace('_', ' ')}",
                company_id=person.company_id,
                person_id=person.id,
            )
    session.commit()
    return PersonOut.model_validate(person)


@router.post("/{person_id}/reply")
def reply(person_id: str, body: Reply, session: DbSession, today: Today) -> PersonOut:
    """They replied: their reach-out ends and the company moves to Replied."""
    person = get_person(session, person_id)
    record_reply(session, person, body.text.strip(), today)
    session.commit()
    return PersonOut.model_validate(person)
