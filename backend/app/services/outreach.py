"""People and moves: ticking steps, finishing and reopening moves, replies, adding people, promoting a company off the
bench, and pulling work forward."""

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import next_weekday, now, weekday_on_or_after
from app.models import Company, Move, MoveStatus, MoveType, Person, PersonStatus, RoleInHire, Stage, Sureness
from app.services import reach
from app.services.history import already_won, record
from app.services.stages import OUT_OF_PLAY, advance, park_skipped, unpark_skipped

EMAIL_TYPES = frozenset({MoveType.EMAIL, MoveType.APPROVER_EMAIL, MoveType.BUMP})
# The kinds of move a reach row replaces; one of these with nobody attached means "find who to write to first".
OUTREACH_TYPES = frozenset(
    {MoveType.COMMENT, MoveType.CONNECT, MoveType.EMAIL, MoveType.APPROVER_EMAIL, MoveType.BUMP, MoveType.LINKEDIN_DM}
)
NOT_YET_IN_TOUCH = frozenset({PersonStatus.NONE, PersonStatus.REQUESTED, PersonStatus.CONNECTED})
REPLY_XP = 10
STEP_LABEL = {
    reach.Step.EMAIL: "Emailed",
    reach.Step.REQUEST: "Sent a connection request to",
    reach.Step.ACCEPTED: "Connection accepted:",
    reach.Step.DM: "Sent a LinkedIn message to",
    reach.Step.BUMP: "Bumped",
}


class RuleError(ValueError):
    """The change breaks a rule; the message says which, in words the user can act on. The API answers 409."""


class NotFoundError(RuleError):
    """Something the change refers to isn't there. The API answers 404."""


# ----------------------------------------------------------------------------- reach rows


def refresh(move: Move) -> None:
    """Work out status, due and next for a reach row from its ticks."""
    outcome = reach.evaluate(move.sequence, fallback_due=move.due)
    move.sequence = {**move.sequence, "next": outcome.next}
    if outcome.open:
        move.status = MoveStatus.OPEN
        move.due = outcome.due or move.due
        move.done_at = None
    else:
        move.status = MoveStatus.DONE
        move.done_at = move.done_at or now()


def start_reach(session: Session, person: Person, day0: date) -> Move:
    move = Move(
        company_id=person.company_id,
        person=person,
        type=MoveType.REACH,
        title=f"Reach out to {person.name}",
        due=day0,
        sequence=reach.new_sequence(day0),
    )
    refresh(move)
    session.add(move)
    return move


def tick_step(session: Session, move: Move, step: reach.Step, value: date | str | None, today: date) -> Move:
    """Mark a step done on a day (today by default), n/a, or not done. Unticking doesn't undo what the tick changed
    (the stage, the person's status), because those may have changed for other reasons since."""
    if move.type is not MoveType.REACH:
        raise RuleError("Only a reach-out has steps.")
    if isinstance(value, date) and value > today:
        raise RuleError("A step can't be done in the future.")
    move.sequence = reach.tick(move.sequence, step, value)
    if isinstance(value, date):
        _after_step(session, move, step, value)
    refresh(move)
    return move


def _after_step(session: Session, move: Move, step: reach.Step, day: date) -> None:
    person = move.person
    if person is None:
        return
    if step in (reach.Step.EMAIL, reach.Step.BUMP, reach.Step.DM):
        advance(session, move.company, Stage.CONTACTED)
    if step is reach.Step.EMAIL and person.status in NOT_YET_IN_TOUCH and person.emailed_at is None:
        person.emailed_at = day
    if step is reach.Step.REQUEST and person.status is PersonStatus.NONE:
        person.status = PersonStatus.REQUESTED
    if step is reach.Step.ACCEPTED and person.status in (PersonStatus.NONE, PersonStatus.REQUESTED):
        person.status = PersonStatus.CONNECTED
    record(
        session,
        "done",
        f"{STEP_LABEL[step]} {person.name}",
        company_id=move.company_id,
        person_id=person.id,
        move_id=move.id,
    )


# ----------------------------------------------------------------------------- any move


@dataclass(frozen=True)
class MoveChange:
    title: str | None = None
    notes: str | None = None
    url: str | None = None
    due: date | None = None
    status: MoveStatus | None = None
    skip_reason: str | None = None


def change_move(session: Session, move: Move, change: MoveChange, today: date) -> Move:
    if change.title is not None:
        move.title = change.title
    if change.notes is not None:
        move.notes = change.notes
    if change.url is not None:
        move.url = change.url or None
    if move.type is MoveType.REACH:
        _change_reach(session, move, change, today)
    else:
        _change_other(session, move, change, today)
    return move


def _change_reach(session: Session, move: Move, change: MoveChange, today: date) -> None:
    if change.status in (MoveStatus.DONE, MoveStatus.SKIPPED):
        move.sequence = reach.close(move.sequence, today)
        record(session, change.status.value, f"Closed: {move.title}", **_refs(move))
    elif change.status is MoveStatus.OPEN:
        move.sequence = reach.reopen(move.sequence)
        record(session, "reopen", f"Reopened: {move.title}", **_refs(move))
    if change.due is not None:
        move.sequence = reach.reschedule(move.sequence, change.due)
        record(session, "reschedule", f"Moved to {change.due:%a %b %-d}: {move.title}", **_refs(move))
    refresh(move)


def _change_other(session: Session, move: Move, change: MoveChange, today: date) -> None:
    if change.skip_reason is not None:
        move.skip_reason = change.skip_reason or None
    if change.status is not None and change.status is not move.status:
        move.status = change.status
        if change.status is MoveStatus.OPEN:
            move.done_at = None
            record(session, "reopen", f"Reopened: {move.title}", **_refs(move))
            if move.type is MoveType.APPLY:
                move.skip_reason = None
                unpark_skipped(session, move.company)
        else:
            move.done_at = now()
            word = "Done" if change.status is MoveStatus.DONE else "Skipped"
            record(session, change.status.value, f"{word}: {move.title}", **_refs(move))
            if change.status is MoveStatus.DONE:
                _after_done(session, move, today)
            elif move.type is MoveType.APPLY and not move.skip_reason:
                park_skipped(session, move.company, today)
    if change.due is not None and change.due != move.due:
        move.due = change.due
        record(session, "reschedule", f"Moved to {change.due:%a %b %-d}: {move.title}", **_refs(move))


def _after_done(session: Session, move: Move, today: date) -> None:
    person = move.person
    if move.type in EMAIL_TYPES:
        advance(session, move.company, Stage.CONTACTED)
        if person is not None and person.status in NOT_YET_IN_TOUCH and person.emailed_at is None:
            person.emailed_at = today
    elif move.type is MoveType.CONNECT and person is not None and person.status is PersonStatus.NONE:
        person.status = PersonStatus.REQUESTED
    elif move.type is MoveType.CALL:
        advance(session, move.company, Stage.CALL_BOOKED)


def _refs(move: Move) -> dict[str, Any]:
    return {"company_id": move.company_id, "person_id": move.person_id, "move_id": move.id}


@dataclass(frozen=True)
class NewMove:
    type: MoveType
    title: str
    due: date
    company_id: str | None = None
    person_id: str | None = None
    notes: str = ""
    url: str | None = None


def add_move(session: Session, new: NewMove) -> Move:
    if new.type is MoveType.REACH:
        raise RuleError("Add the person instead; they get a reach-out of their own.")
    company = session.get(Company, new.company_id) if new.company_id else None
    if new.company_id and company is None:
        raise NotFoundError("That company isn't in the tracker.")
    person = session.get(Person, new.person_id) if new.person_id else None
    if new.person_id and (person is None or person.company_id != new.company_id):
        raise NotFoundError("That person isn't at this company.")
    move = Move(
        company=company,
        person=person,
        type=new.type,
        title=new.title,
        due=new.due,
        notes=new.notes,
        url=new.url,
    )
    session.add(move)
    session.flush()
    record(session, "action", f"Added: {move.title} (due {move.due:%a %b %-d})", **_refs(move))
    return move


def delete_move(session: Session, move: Move) -> None:
    record(session, "deleted", f"Deleted: {move.title}", company_id=move.company_id, person_id=move.person_id)
    session.delete(move)


def pull_forward(session: Session, n: int, today: date) -> list[Move]:
    """Bring the next `n` open moves to today. Only companies still in play, and only moves that can move: a reach
    row's first touches (its Day 0 moves with it), not a follow-up that's waiting on its timing."""
    rows = session.scalars(
        select(Move)
        .outerjoin(Company, Move.company_id == Company.id)
        .where(
            Move.status == MoveStatus.OPEN,
            Move.due > today,
            (Company.id.is_(None)) | (Company.stage.not_in(OUT_OF_PLAY)),
        )
        .order_by(Move.due, Move.created_at, Move.id)
        .limit(n * 4)
    ).all()
    pulled: list[Move] = []
    for move in rows:
        if len(pulled) == n:
            break
        if move.type is MoveType.REACH:
            if not reach.first_touches_pending(move.sequence):
                continue
            move.sequence = reach.reschedule(move.sequence, today)
            refresh(move)
        else:
            move.due = today
        pulled.append(move)
    if pulled:
        noun = "move" if len(pulled) == 1 else "moves"
        record(session, "pull", f"Pulled {len(pulled)} {noun} forward to today")
    return pulled


# ----------------------------------------------------------------------------- people


@dataclass(frozen=True)
class NewPerson:
    company_id: str
    name: str
    title: str = ""
    linkedin: str | None = None
    location: str = ""
    email: str | None = None
    role_in_hire: RoleInHire = RoleInHire.HIRING_MANAGER
    sureness: Sureness | None = None
    why: str = ""


def add_person(session: Session, new: NewPerson, today: date) -> Person:
    """Add someone at a company, with a reach-out of their own. If the company had a "find who to write to" move, the
    first person found takes over its date, and the move is marked done (not deleted, so it stays in the history)."""
    company = session.get(Company, new.company_id)
    if company is None:
        raise NotFoundError("That company isn't in the tracker.")
    name = " ".join(new.name.split())
    taken = session.scalar(
        select(Person.id).where(Person.company_id == company.id, Person.name.ilike(name.replace("%", r"\%")))
    )
    if taken:
        raise RuleError(f"{name} is already at {company.name}.")
    person = Person(
        company=company,
        name=name,
        title=new.title,
        linkedin=new.linkedin,
        location=new.location,
        email=new.email,
        role_in_hire=new.role_in_hire,
        sureness=new.sureness,
        why=new.why,
    )
    session.add(person)
    session.flush()

    finders = session.scalars(
        select(Move).where(
            Move.company_id == company.id,
            Move.person_id.is_(None),
            Move.status == MoveStatus.OPEN,
            Move.type.in_(OUTREACH_TYPES),
        )
    ).all()
    day0 = min([m.due for m in finders], default=today)
    if company.stage in OUT_OF_PLAY:
        day0 = max(day0, today)
    start_reach(session, person, day0)
    for finder in finders:
        finder.status = MoveStatus.DONE
        finder.done_at = now()
        finder.notes = f"{finder.notes} [found: {name}]".strip()
    session.flush()
    record(session, "research", f"{company.name}: added {name}", company_id=company.id, person_id=person.id)
    return person


def record_reply(session: Session, person: Person, text: str, today: date) -> bool:
    """They replied. Their reach-out ends, any queued nudges to them are skipped, and the company moves to Replied.
    The first reply from each person earns XP once (a status set back and forth earns nothing more); logging it again
    still closes anything reopened since. Returns whether this is the first time they're marked replied."""
    first = person.status is not PersonStatus.REPLIED
    person.status = PersonStatus.REPLIED
    tag = f"reply:{person.id}"
    win = not already_won(session, person.company_id, tag)
    words = f"{person.name} replied" + (f": {text}" if text else "")
    record(
        session,
        "reply",
        words,
        company_id=person.company_id,
        person_id=person.id,
        xp=REPLY_XP if win else 0,
        tag=tag if win else None,
    )
    advance(session, person.company, Stage.REPLIED)
    for move in session.scalars(select(Move).where(Move.person_id == person.id)):
        if move.type is MoveType.REACH:
            move.sequence = reach.mark_replied(move.sequence, today)
            refresh(move)
        elif move.status is MoveStatus.OPEN and move.type in (MoveType.BUMP, MoveType.LINKEDIN_DM):
            move.status = MoveStatus.SKIPPED
            move.done_at = now()
            move.notes = f"{move.notes} [skipped: they replied]".strip()
    return first


def mark_left(session: Session, person: Person, today: date) -> None:
    """They've left the company: their open reach-out closes."""
    person.left = True
    for move in session.scalars(
        select(Move).where(Move.person_id == person.id, Move.type == MoveType.REACH, Move.status == MoveStatus.OPEN)
    ):
        move.sequence = reach.close(move.sequence, today)
        move.notes = f"{move.notes} They've left the company.".strip()
        refresh(move)
    record(session, "contact", f"{person.name} has left the company", company_id=person.company_id, person_id=person.id)


# ----------------------------------------------------------------------------- companies


def promote(session: Session, company: Company, wave: str, today: date) -> Company:
    """Bring a company off the bench: everyone still there gets a reach-out from the next working day, and there's a
    move to find the approver and hiring manager."""
    if company.stage is not Stage.BENCH:
        raise RuleError(f"{company.name} isn't on the bench.")
    company.wave = wave
    company.stage = Stage.RESEARCHING
    day0 = next_weekday(today)
    people = [p for p in company.people if not p.left]
    have = set(
        session.scalars(select(Move.person_id).where(Move.company_id == company.id, Move.type == MoveType.REACH)).all()
    )
    for person in people:
        if person.id not in have:
            start_reach(session, person, day0)
    session.add(
        Move(
            company=company,
            type=MoveType.RESEARCH,
            title=f"Find the approver and hiring manager at {company.name}",
            due=weekday_on_or_after(today),
        )
    )
    if not people:
        session.add(
            Move(
                company=company,
                type=MoveType.EMAIL,
                title=f"Day 0 email to the {company.name} hiring manager (add them in People first)",
                due=day0,
            )
        )
    record(session, "wave", f"{company.name}: off the bench, into wave {wave}", company_id=company.id)
    return company
