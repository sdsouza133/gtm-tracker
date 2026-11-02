"""Deleting personal data after 30 days.

The `retention` job does it, once an hour. A worker's housekeeping queues the job whenever no copy is waiting, and
after each round the job waits an hour for the next (deferred, so it never uses up its attempts). Its dedupe key
lets one copy at most wait or run, so two workers never delete at once; an advisory lock makes that hold for any
other caller too.

A round deletes, in one transaction (if anything fails, nothing is deleted and the job tries again):

1. A run's list once its results expire, EVENTS_RESULTS_DAYS (at most 30) after it was ready: the run is marked
   expired and its leads are deleted. A run that failed or was canceled loses its leads 30 days after it stopped. A
   run still under way that hasn't moved for 30 days (its jobs can't run, say, while a key is missing) is stopped,
   and loses its leads in the same round.
2. Shared data that no list holds: posts fetched more than 30 days ago (their links to events and their labels go
   with them), and people whose Apollo lookup and email check are more than 30 days old or never happened. The
   database refuses to delete a lead's person or post while the lead exists, so a list that is still shown keeps
   everyone on it, even when a run picks someone at the very moment their data is deleted: that round fails, and
   the next one leaves them be.
3. Labels made and searches run more than 30 days ago, and jobs that finished more than 30 days ago.

Everything goes by age, so a second round straight after the first deletes nothing. Only counts are logged.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, and_, delete, exists, func, or_, select, update
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.events import queue
from app.events.db import rowcount
from app.events.models import (
    Base,
    Job,
    JobStatus,
    Lead,
    Person,
    Post,
    PostLabel,
    Run,
    RunStatus,
    SearchCache,
)
from app.events.pipeline.base import Defer, JobContext, Outcome, Payload

log = logging.getLogger(__name__)

RETENTION = "retention"
EVERY = timedelta(hours=1)
KEPT_FOR = timedelta(days=30)
EXPIRED = "This list has expired, and the personal data in it has been deleted."
STALLED = "This run stopped: nothing happened on it for 30 days, so the personal data it held has been deleted."
STOPPED = (RunStatus.FAILED, RunStatus.CANCELED)
UNDER_WAY = (
    RunStatus.ANALYZING,
    RunStatus.AWAITING_APPROVAL,
    RunStatus.COLLECTING,
    RunStatus.WAITING_FOR_BUDGET,
    RunStatus.QUALIFYING,
    RunStatus.ENRICHING,
)
FINISHED_JOBS = (JobStatus.DONE, JobStatus.FAILED)


def schedule(session: Session, *, now: datetime) -> bool:
    """Queue the retention job unless a copy is already waiting or running. True when this call queued it."""
    return queue.enqueue(session, RETENTION, run_after=now, dedupe_key=RETENTION) is not None


def retention(ctx: JobContext, session: Session, _payload: Payload) -> Outcome:
    """One round, then wait an hour for the next."""
    deleted = forget(session, now=ctx.now())
    log.info("old data deleted", extra=deleted)
    return Defer(EVERY)


def forget(session: Session, *, now: datetime) -> dict[str, int]:
    """Delete what has been kept long enough. Returns how many rows of each kind went (runs: how many expired or
    were stopped)."""
    session.execute(select(func.pg_advisory_xact_lock(func.hashtext(RETENTION))))
    cutoff = now - KEPT_FOR
    expired = session.execute(
        update(Run)
        .where(Run.status == RunStatus.READY, Run.results_expire_at <= now)
        .values(status=RunStatus.EXPIRED, status_detail=EXPIRED)
        .execution_options(synchronize_session=False)
    )
    stalled = session.scalars(
        update(Run)
        .where(Run.status.in_(UNDER_WAY), Run.updated_at < cutoff)
        .values(status=RunStatus.FAILED, status_detail=STALLED, error="no progress for 30 days", completed_at=now)
        .returning(Run.id)
        .execution_options(synchronize_session=False)
    ).all()
    ended = or_(
        Run.status == RunStatus.EXPIRED,
        and_(Run.status.in_(STOPPED), func.coalesce(Run.completed_at, Run.updated_at) < cutoff),
        Run.id.in_(stalled),
    )
    return {
        "expired_runs": rowcount(expired),
        "stalled_runs": len(stalled),
        # Lists first, so the people and posts only they held go in this same round.
        "leads": _delete(session, Lead, Lead.run_id.in_(select(Run.id).where(ended))),
        "labels": _delete(session, PostLabel, PostLabel.created_at < cutoff),
        "posts": _delete(session, Post, Post.fetched_at < cutoff, ~exists().where(Lead.post_id == Post.id)),
        "people": _delete(
            session,
            Person,
            _before(Person.enriched_at, cutoff),
            _before(Person.email_checked_at, cutoff),
            ~exists().where(Lead.person_id == Person.id),
        ),
        "searches": _delete(session, SearchCache, SearchCache.fetched_at < cutoff),
        "jobs": _delete(session, Job, Job.status.in_(FINISHED_JOBS), Job.updated_at < cutoff),
    }


def _delete(session: Session, table: type[Base], *where: ColumnElement[bool]) -> int:
    statement = delete(table).where(*where).execution_options(synchronize_session=False)
    return rowcount(session.execute(statement))


def _before(column: InstrumentedAttribute[datetime | None], cutoff: datetime) -> ColumnElement[bool]:
    """Never, or longer ago than the cutoff."""
    return or_(column.is_(None), column < cutoff)
