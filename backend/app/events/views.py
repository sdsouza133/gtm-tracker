"""What the tracker's Events pages read and change: a run's progress, its plan, its list, the day's spend, and the
switch for new runs. `app/api/events.py` turns these into JSON; nothing here knows about HTTP.

While a run works, its page shows a few steps and, once the search is under way, what it has found so far. While it
awaits approval, its page is the plan: the ICP Claude read from the site, and the events found, the first three
picked, each with the LinkedIn searches that would run. Once it has finished, its page is the list.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import Select, distinct, func, or_, select
from sqlalchemy.orm import Session

from app.events import budget, flags, start
from app.events.config import EventsSettings
from app.events.models import (
    BudgetDay,
    Event,
    EventPost,
    Job,
    JobStatus,
    Lead,
    Person,
    Post,
    PostLabel,
    Run,
    RunEvent,
    RunEventStatus,
    RunStatus,
)
from app.events.pipeline import analyze, collect, qualify, runs
from app.events.pipeline.keywords import build_queries
from app.events.schemas import (
    MAX_QUERIES,
    MOST_TELLING,
    QUALIFYING_LABELS,
    ApprovedEvent,
    EventFields,
    Icp,
    Query,
    ShortText,
    SiteAnalysis,
    Url,
)

WORKING = frozenset(
    {RunStatus.ANALYZING, RunStatus.COLLECTING, RunStatus.WAITING_FOR_BUDGET, RunStatus.QUALIFYING, RunStatus.ENRICHING}
)
"""While a run is in one of these, its page checks back every few seconds."""
FINISHED = frozenset({RunStatus.READY, RunStatus.FAILED, RunStatus.CANCELED, RunStatus.EXPIRED})
LABELS = {
    RunStatus.ANALYZING: "Getting the plan ready",
    RunStatus.AWAITING_APPROVAL: "Plan ready to review",
    RunStatus.COLLECTING: "Finding people",
    RunStatus.WAITING_FOR_BUDGET: "Waiting for tomorrow's budget",
    RunStatus.QUALIFYING: "Finding people",
    RunStatus.ENRICHING: "Finding people",
    RunStatus.READY: "List ready",
    RunStatus.FAILED: "Stopped",
    RunStatus.CANCELED: "Canceled",
    RunStatus.EXPIRED: "Expired",
}
CANCELED = "Canceled before it finished."
SEARCH_STEPS = ["Searching LinkedIn posts about the events", "Checking who's really going", "Finding verified emails"]
SEARCH_STEP = {
    RunStatus.COLLECTING: 0,
    RunStatus.WAITING_FOR_BUDGET: 0,
    RunStatus.QUALIFYING: 1,
    RunStatus.ENRICHING: 2,
}
USUAL_DETAILS = frozenset(
    {start.READING_SITE, analyze.FINDING_EVENTS, collect.SEARCHING, collect.READING_POSTS, qualify.ENRICHING}
)
"""What a working run says while all is well: the steps already show it. Anything else (waiting for the day's budget,
say) is worth a line of its own."""
ATTENDANCE = {"speaking": "Speaking", "exhibiting": "Exhibiting", "attending": "Going", "attended": "Went"}
PRESELECTED = collect.MAX_EVENTS
"""The first suggestions start out picked, so a plan that looks right can be approved as it stands."""
MAX_OWN_EVENTS = 3
MAX_PICKED = collect.MAX_EVENTS
MAX_SEARCHES = MAX_QUERIES
APPROVED_FIELDS = ("name", "short_name", "start_date", "end_date", "location", "url", "queries")
_URL: TypeAdapter[str] = TypeAdapter(Url)
_NAME: TypeAdapter[str] = TypeAdapter(ShortText)
_QUERY: TypeAdapter[str] = TypeAdapter(Query)


class PlanError(ValueError):
    """The plan as sent can't be saved; the message says what to change."""


class NotEditableError(ValueError):
    """The run isn't awaiting approval any more (approved already, say, or stopped)."""


# ------------------------------------------------------------------------------------------------------ progress
@dataclass(frozen=True)
class Progress:
    steps: list[str]
    step: int  # the one under way; those before it are done
    note: str  # anything unusual the run says, such as waiting for tomorrow's budget


@dataclass(frozen=True)
class Found:
    """What the search has found so far, and how far along it is."""

    posts: int  # found for the run's events
    people: int  # whose posts show them at one of the events
    emails: int  # verified, of the people still in the running
    percent: int


def progress(run: Run) -> Progress | None:
    """How far a working run has got, as steps; None for one that isn't working."""
    note = "" if run.status_detail in USUAL_DETAILS else (run.status_detail or "")
    if run.status == RunStatus.ANALYZING:
        return Progress(
            [f"Reading {run.domain}", "Finding events their buyers go to"], 0 if run.icp is None else 1, note
        )
    if run.status in SEARCH_STEP:
        return Progress(SEARCH_STEPS, SEARCH_STEP[run.status], note)
    return None


def found_so_far(session: Session, run: Run, accepted: tuple[str, ...]) -> Found:
    """The counters for a run in its search, and how far along it is: each of its three steps is a third of the way,
    and within a step, the share of events searched, of posts read, or of people looked up."""
    events = select(RunEvent.event_id).where(RunEvent.run_id == run.id)
    posts = _count(session, select(func.count(distinct(EventPost.post_id))).where(EventPost.event_id.in_(events)))
    people = _count(
        session,
        select(func.count(distinct(Post.author_url)))
        .join(PostLabel, PostLabel.post_id == Post.id)
        .where(
            PostLabel.event_id.in_(events),
            PostLabel.label.in_([str(label) for label in QUALIFYING_LABELS]),
            Post.author_kind == "person",
        ),
    )
    leads = select(func.count()).select_from(Lead).join(Person, Person.id == Lead.person_id)
    leads = leads.where(Lead.run_id == run.id)
    emails = _count(session, leads.where(Lead.exclude_reason.is_(None), Person.email_status.in_(accepted)))
    step = SEARCH_STEP.get(run.status, 0)
    if step == 0:  # searching: the events done (or given up on)
        total = select(func.count()).select_from(RunEvent).where(RunEvent.run_id == run.id)
        done = total.where(RunEvent.status.in_([RunEventStatus.DONE, RunEventStatus.FAILED]))
        share = _share(_count(session, done), _count(session, total))
    elif step == 1:  # reading: the posts by people labeled
        posts_by_people = (
            select(func.count())
            .select_from(EventPost)
            .join(Post, Post.id == EventPost.post_id)
            .where(EventPost.event_id.in_(events), Post.author_kind == "person")
        )
        labeled = select(func.count()).select_from(PostLabel).where(PostLabel.event_id.in_(events))
        share = _share(_count(session, labeled), _count(session, posts_by_people))
    else:  # finding emails: the people looked up, of those not ruled out before
        to_look_up = leads.where(or_(Lead.exclude_reason.is_(None), Person.enriched_at.is_not(None)))
        share = _share(_count(session, leads.where(Person.enriched_at.is_not(None))), _count(session, to_look_up))
    return Found(posts, people, emails, percent=max(2, min(99, round((step + share) * 100 / len(SEARCH_STEPS)))))


def _count(session: Session, query: Select[int]) -> int:
    return session.scalar(query) or 0


def _share(part: int, whole: int) -> float:
    return min(1.0, part / whole) if whole else 0.0


# ---------------------------------------------------------------------------------------------------------- plan
def analysis(run: Run) -> SiteAnalysis | None:
    """What Claude read from the site, once it has."""
    return SiteAnalysis.model_validate(run.icp) if run.icp else None


def plan_events(run: Run, *, today: date) -> list[dict[str, Any]]:
    """The run's events as its page shows them: each as stored, with whether it's picked (the first three start out
    picked), its searches, and whether it's over already (then the search looks for the people who went)."""
    shown = []
    for i, event in enumerate(run.suggested_events or []):
        start_day, end_day = _day(event.get("start_date")), _day(event.get("end_date"))
        last = end_day or start_day
        shown.append(
            {
                **event,
                "index": i,
                "picked": bool(event.get("picked", i < PRESELECTED)),
                "queries": list(event.get("queries") or []),
                "own": event.get("source") == "requester",
                "past": last is not None and last < today,
            }
        )
    return shown


def save_plan(
    session: Session, run_id: uuid.UUID, icp: Icp, picks: list[tuple[bool, list[str]]], *, approve: bool, now: datetime
) -> Run | None:
    """Save the edited ICP and each event's pick and searches (in the order the run lists its events), and start
    collecting when `approve`. None for a run that isn't there. The caller commits."""
    run = runs.locked(session, run_id)  # as it is now, and no other request changes it until this one commits
    if run is None:
        return None
    if run.status != RunStatus.AWAITING_APPROVAL or run.icp is None:
        raise NotEditableError("This run's plan can't be changed any more.")
    stored = list(run.suggested_events or [])
    if len(picks) != len(stored):
        raise PlanError("The plan changed while you were editing it. Reload the page and try again.")
    events = []
    for i, (event, (picked, typed)) in enumerate(zip(stored, picks, strict=True)):
        queries = _unique(typed)
        if (picked or queries) and not _searches_ok(queries):
            raise PlanError(f"Give {event['name']} 1 to {MAX_QUERIES} searches, one per line (event {i + 1}).")
        events.append({**event, "picked": picked, "queries": queries})
    picked_count = sum(1 for event in events if event["picked"])
    if picked_count > collect.MAX_EVENTS:
        raise PlanError(f"Pick up to {collect.MAX_EVENTS} events.")
    if approve and picked_count == 0:
        raise PlanError("Pick at least one event to search, or add one of your own.")
    run.icp = SiteAnalysis.model_validate(run.icp).model_copy(update={"icp": icp}).model_dump(mode="json")
    run.suggested_events = events
    if approve:
        approved = [_approved(event) for event in events if event["picked"]]
        collect.approve(session, run.id, approved, now=now)
    return run


def add_event(
    session: Session, run_id: uuid.UUID, name: str, when: date | None, url: str | None, *, now: datetime
) -> Run | None:
    """Add an event you know to the plan, with searches written for it the way they're written for the ones found,
    picked if there's room. None for a run that isn't there. The caller commits."""
    run = runs.locked(session, run_id)
    if run is None:
        return None
    if run.status != RunStatus.AWAITING_APPROVAL:
        raise NotEditableError("This run's plan can't be changed any more.")
    name = " ".join(name.split())
    if not _valid(_NAME, name):
        raise PlanError("Give the event's name, in up to 120 characters.")
    link = (url or "").strip() or None
    if link is not None and "://" not in link:
        link = f"https://{link}"
    if link is not None and (any(c.isspace() for c in link) or not _valid(_URL, link)):
        raise PlanError("Enter the event's web address, like https://example.com/event.")
    events = plan_events(run, today=now.date())
    if sum(1 for event in events if event["own"]) >= MAX_OWN_EVENTS:
        raise PlanError(f"You can add up to {MAX_OWN_EVENTS} events of your own.")
    key = collect.event_key(name, when)
    if any(collect.event_key(event["name"], _day(event.get("start_date"))) == key for event in events):
        raise PlanError("That event is already in the plan.")
    basics = EventFields(name=name, start_date=when, end_date=when)
    queries = build_queries(basics, today=now.date())
    picked = sum(1 for event in events if event["picked"]) < collect.MAX_EVENTS
    added = {**basics.model_dump(mode="json"), "url": link, "source": "requester", "picked": picked, "queries": queries}
    run.suggested_events = [*[_stored(event) for event in events], added]
    return run


def _stored(event: dict[str, Any]) -> dict[str, Any]:
    """An event as `plan_events` shows it, back as stored (its pick made explicit)."""
    return {k: v for k, v in event.items() if k not in ("index", "own", "past")}


def _approved(event: dict[str, Any]) -> ApprovedEvent:
    fields = {name: event.get(name) for name in APPROVED_FIELDS}
    return ApprovedEvent.model_validate(
        {**fields, "hashtags": event.get("hashtags") or [], "source": event.get("source", "suggested")}
    )


def _unique(lines: list[str]) -> list[str]:
    seen: dict[str, str] = {}
    for line in lines:
        clean = line.strip()
        if clean:
            seen.setdefault(clean.casefold(), clean)
    return list(seen.values())


def _searches_ok(queries: list[str]) -> bool:
    return 1 <= len(queries) <= MAX_QUERIES and all(_valid(_QUERY, query) for query in queries)


def _valid(adapter: TypeAdapter[str], value: str) -> bool:
    try:
        adapter.validate_python(value)
    except ValidationError:
        return False
    return True


def _day(value: Any) -> date | None:
    return date.fromisoformat(value) if isinstance(value, str) and value else None


# ---------------------------------------------------------------------------------------------------------- list
@dataclass(frozen=True)
class Row:
    name: str
    title: str
    company: str
    email: str
    linkedin_url: str
    event: str
    attendance: str
    post_url: str
    score: int
    reasons: list[str]


def expired(run: Run, now: datetime) -> bool:
    return run.status == RunStatus.EXPIRED or (run.results_expire_at is not None and run.results_expire_at <= now)


def rows(session: Session, run: Run) -> list[Row]:
    """The run's list, best first: the highest ICP score, then the most telling post (a speaker before an attendee),
    then by name."""
    found = session.execute(
        select(Lead, Person, Event.name, Post.url)
        .join(Person, Person.id == Lead.person_id)
        .join(Event, Event.id == Lead.event_id)
        .join(Post, Post.id == Lead.post_id)
        .where(Lead.run_id == run.id, Lead.included.is_(True))
    )
    listed = [
        Row(
            name=person.name or "",
            title=person.title or "",
            company=person.company_name or "",
            email=person.email or "",
            linkedin_url=_web(person.linkedin_url),
            event=event,
            attendance=ATTENDANCE.get(lead.attendance, lead.attendance),
            post_url=_web(post_url),
            score=lead.icp_score,
            reasons=[str(reason) for reason in lead.icp_reasons],
        )
        for lead, person, event, post_url in found
    ]
    telling = {ATTENDANCE[str(label)]: rank for rank, label in enumerate(MOST_TELLING)}
    return sorted(listed, key=lambda row: (-row.score, telling.get(row.attendance, len(telling)), row.name.casefold()))


def _web(url: str | None) -> str:
    """The address if it's a web page, so a link can't run script ('javascript:...')."""
    return url if url and url.lower().startswith(("https://", "http://")) else ""


# ---------------------------------------------------------------------------------------------- the whole tool
@dataclass(frozen=True)
class Today:
    spent_usd: Decimal
    reserved_usd: Decimal
    cap_usd: Decimal
    runs_started: int


@dataclass(frozen=True)
class Queue:
    due: int
    later: int
    running: int
    failed: int


def today(session: Session, settings: EventsSettings, now: datetime) -> Today:
    """Today's spend (the UTC day the daily cap counts) against the cap, and the runs started today."""
    day = budget.utc_day(now)
    row = session.get(BudgetDay, day)
    spent, reserved = (row.spent_usd, row.reserved_usd) if row is not None else (Decimal(0), Decimal(0))
    midnight = datetime(day.year, day.month, day.day, tzinfo=UTC)
    started = session.scalar(select(func.count()).select_from(Run).where(Run.created_at >= midnight)) or 0
    return Today(spent, reserved, settings.daily_cap_usd, started)


def queue(session: Session, now: datetime) -> Queue:
    counts: dict[JobStatus, int] = dict(session.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    due = session.scalar(
        select(func.count()).select_from(Job).where(Job.status == JobStatus.QUEUED, Job.run_after <= now)
    )
    queued = counts.get(JobStatus.QUEUED, 0)
    return Queue(
        due=due or 0,
        later=queued - (due or 0),
        running=counts.get(JobStatus.RUNNING, 0),
        failed=counts.get(JobStatus.FAILED, 0),
    )


def cancel(session: Session, run_id: uuid.UUID, *, now: datetime) -> Run | None:
    """Stop a run that hasn't finished. Every step checks the run's status before it starts anything, so this is all
    it takes; a call already under way finishes and its cost is counted. None for a run that isn't there; a finished
    run is left as it is. The caller commits."""
    run = runs.locked(session, run_id)
    if run is None or run.status in FINISHED:
        return run
    run.status, run.status_detail, run.completed_at = RunStatus.CANCELED, CANCELED, now
    run.error = "; ".join(filter(None, [run.error, "canceled from the Events page"]))
    return run


def pause_new_runs(session: Session, *, on: bool, now: datetime) -> None:
    flags.turn(session, flags.NEW_RUNS_PAUSED, on=on, now=now)
