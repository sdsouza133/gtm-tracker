"""The events tool: start a run for a company's website, review and approve its plan, follow it, and read its list.

Every route needs sign-in. While the tracker runs with OPEN_ACCESS (no sign-in), the tool is off, apart from the
overview saying so: its lists hold work emails, which never sit in a tracker anyone can open. The work itself
happens in the background (`app/events/worker.py`); these routes read and change what it works from.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import AppSettings, DbSession, SignedIn
from app.events import start, views
from app.events.config import EventsSettings, get_events_settings
from app.events.models import Run, RunStatus
from app.models import Company
from app.schemas import (
    EventAdd,
    EventFound,
    EventLeadOut,
    EventPlan,
    EventPlanSave,
    EventProgress,
    EventRunCreate,
    EventRunOut,
    EventRunSummary,
    EventsHome,
    EventsQueue,
    EventsSwitch,
    EventsToday,
    PlanEvent,
)

log = logging.getLogger("gtm_tracker.events")

router = APIRouter(prefix="/api/events", tags=["events"], dependencies=[SignedIn])

LIST_LIMIT = 50
OFF_WITHOUT_SIGN_IN = "The events tool is off while the tracker has no sign-in (OPEN_ACCESS): its lists hold emails."


def get_now() -> datetime:
    return datetime.now(UTC)


Now = Annotated[datetime, Depends(get_now)]
Events = Annotated[EventsSettings, Depends(get_events_settings)]


def _sign_in_on(settings: AppSettings) -> None:
    """The tool is off without sign-in. A dependency, so it answers before the request body is even read."""
    if settings.open_access:
        raise HTTPException(status.HTTP_409_CONFLICT, OFF_WITHOUT_SIGN_IN)


SignInOn = Depends(_sign_in_on)


def _run(session: Session, run_id: uuid.UUID) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That run isn't here (runs are deleted after 30 days).")
    return run


def _company_names(session: Session, runs: list[Run]) -> dict[str, str]:
    ids = {run.company_id for run in runs if run.company_id}
    if not ids:
        return {}
    return dict(session.execute(select(Company.id, Company.name).where(Company.id.in_(ids))).all())


def _summary(run: Run, names: dict[str, str]) -> EventRunSummary:
    return EventRunSummary(
        id=str(run.id),
        website=run.website_url,
        domain=run.domain,
        company_id=run.company_id,
        company_name=names.get(run.company_id or ""),
        status=run.status.value,
        label=views.LABELS[run.status],
        detail=run.status_detail or "",
        created=run.created_at,
        completed=run.completed_at,
        leads=run.leads_count,
        spent_usd=float(run.spent_usd),
        budget_usd=float(run.budget_usd),
    )


def _out(session: Session, run: Run, settings: EventsSettings, now: datetime) -> EventRunOut:
    session.flush()
    session.refresh(run)  # server-side defaults (created_at) and what the worker wrote since
    shown = views.progress(run)
    searching = run.status in views.SEARCH_STEP
    found = views.found_so_far(session, run, settings.accepted_email_statuses) if searching else None
    analysis = views.analysis(run)
    plan = None
    if analysis is not None and run.status != RunStatus.ANALYZING:
        plan = EventPlan(
            company_name=analysis.company_name,
            offering=analysis.offering,
            icp=analysis.icp,
            events=[PlanEvent.model_validate(event) for event in views.plan_events(run, today=now.date())],
            max_picked=views.MAX_PICKED,
            max_queries=views.MAX_SEARCHES,
        )
    return EventRunOut(
        **_summary(run, _company_names(session, [run])).model_dump(),
        error=run.error or "",
        working=run.status in views.WORKING,
        progress=EventProgress(steps=shown.steps, step=shown.step, note=shown.note) if shown else None,
        found=EventFound(posts=found.posts, people=found.people, emails=found.emails, percent=found.percent)
        if found
        else None,
        plan=plan,
        expires=run.results_expire_at,
    )


@router.get("", response_model=EventsHome)
def overview(
    session: DbSession, settings: AppSettings, events: Events, now: Now, company_id: str | None = None
) -> EventsHome:
    """Whether the tool can run, today's spend against the daily cap, the queue, and the latest runs (for one
    company, given its id)."""
    query = select(Run).order_by(Run.created_at.desc()).limit(LIST_LIMIT)
    if company_id is not None:
        query = query.where(Run.company_id == company_id)
    runs = [] if settings.open_access else list(session.scalars(query))
    names = _company_names(session, runs)
    spend, jobs = views.today(session, events, now), views.queue(session, now)
    return EventsHome(
        missing=events.missing(),
        open_access=settings.open_access,
        paused=start.paused(session, events),
        paused_by_setting=events.pause_new_runs,
        run_budget_usd=float(events.run_budget_usd),
        today=EventsToday(
            spent_usd=float(spend.spent_usd),
            reserved_usd=float(spend.reserved_usd),
            cap_usd=float(spend.cap_usd),
            runs_started=spend.runs_started,
        ),
        queue=EventsQueue(due=jobs.due, later=jobs.later, running=jobs.running, failed=jobs.failed),
        runs=[_summary(run, names) for run in runs],
    )


@router.post("/runs", response_model=EventRunOut, status_code=status.HTTP_201_CREATED, dependencies=[SignInOn])
def start_run(body: EventRunCreate, session: DbSession, events: Events, now: Now) -> EventRunOut:
    """Start a run: it reads the site and suggests a plan, which waits for you to approve it before any search."""
    missing = events.missing()
    if missing:
        raise HTTPException(status.HTTP_409_CONFLICT, f"The events tool needs {', '.join(missing)} (set in Railway).")
    if start.paused(session, events):
        raise HTTPException(status.HTTP_409_CONFLICT, "New runs are paused. Turn them back on to start one.")
    if body.company_id is not None and session.get(Company, body.company_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That company isn't in the tracker.")
    try:
        run = start.start_run(session, body.website, company_id=body.company_id, settings=events, now=now)
    except start.NotAWebsiteError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    out = _out(session, run, events, now)
    session.commit()
    log.info("events run started", extra={"run_id": out.id})
    return out


@router.get("/runs/{run_id}", response_model=EventRunOut, dependencies=[SignInOn])
def get_run(run_id: uuid.UUID, session: DbSession, events: Events, now: Now) -> EventRunOut:
    return _out(session, _run(session, run_id), events, now)


@router.put("/runs/{run_id}/plan", response_model=EventRunOut, dependencies=[SignInOn])
def save_plan(run_id: uuid.UUID, body: EventPlanSave, session: DbSession, events: Events, now: Now) -> EventRunOut:
    """Save the plan as edited, and with `approve`, start searching (the only step that spends beyond reading the
    site)."""
    picks = [(event.picked, event.queries) for event in body.events]
    try:
        run = views.save_plan(session, run_id, body.icp, picks, approve=body.approve, now=now)
    except views.NotEditableError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except views.PlanError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That run isn't here.")
    out = _out(session, run, events, now)
    session.commit()
    return out


@router.post("/runs/{run_id}/events", response_model=EventRunOut, dependencies=[SignInOn])
def add_event(run_id: uuid.UUID, body: EventAdd, session: DbSession, events: Events, now: Now) -> EventRunOut:
    """Add an event you know to the plan; its searches are written for you, and it's picked if there's room."""
    try:
        run = views.add_event(session, run_id, body.name, body.day, body.url, now=now)
    except views.NotEditableError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except views.PlanError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That run isn't here.")
    out = _out(session, run, events, now)
    session.commit()
    return out


@router.post("/runs/{run_id}/cancel", response_model=EventRunOut, dependencies=[SignInOn])
def cancel_run(run_id: uuid.UUID, session: DbSession, events: Events, now: Now) -> EventRunOut:
    """Stop a run that hasn't finished. A call already under way finishes, and its cost counts."""
    run = views.cancel(session, run_id, now=now)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That run isn't here.")
    out = _out(session, run, events, now)
    session.commit()
    return out


@router.get("/runs/{run_id}/leads", response_model=list[EventLeadOut], dependencies=[SignInOn])
def leads(run_id: uuid.UUID, session: DbSession, now: Now) -> list[EventLeadOut]:
    """A finished run's list, best first."""
    run = _run(session, run_id)
    if views.expired(run, now):
        raise HTTPException(status.HTTP_410_GONE, "This list has expired, and its personal data has been deleted.")
    if run.status != RunStatus.READY:
        raise HTTPException(status.HTTP_409_CONFLICT, "This run has no list yet.")
    return [
        EventLeadOut(
            name=row.name,
            title=row.title,
            company=row.company,
            email=row.email,
            linkedin=row.linkedin_url,
            event=row.event,
            attendance=row.attendance,
            post=row.post_url,
            score=row.score,
            reasons=row.reasons,
        )
        for row in views.rows(session, run)
    ]


@router.put("/new-runs", status_code=status.HTTP_204_NO_CONTENT, dependencies=[SignInOn])
def switch_new_runs(body: EventsSwitch, session: DbSession, now: Now) -> Response:
    """Hold new runs (runs already started carry on), or let them start again."""
    views.pause_new_runs(session, on=body.paused, now=now)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
