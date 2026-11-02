"""Starting a run: the only way in, now that the tool lives in the tracker behind its sign-in."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.events import domains, flags, queue
from app.events.config import EventsSettings
from app.events.models import Run, RunStatus
from app.events.pipeline.analyze import ANALYZE_SITE

READING_SITE = "Reading the website"


class NotAWebsiteError(ValueError):
    """What was typed isn't a public web address."""


def paused(session: Session, settings: EventsSettings) -> bool:
    """Whether new runs are held: switched off on the Events page, or EVENTS_PAUSE_NEW_RUNS is set."""
    return settings.pause_new_runs or flags.is_on(session, flags.NEW_RUNS_PAUSED)


def start_run(
    session: Session, website: str, *, company_id: str | None, settings: EventsSettings, now: datetime
) -> Run:
    """A run for a company's website, queued to read the site at once. The caller commits."""
    site = domains.website(website)
    if site is None:
        raise NotAWebsiteError("Enter the company's website, for example acme.com.")
    url, domain = site
    run = Run(
        company_id=company_id,
        domain=domain,
        website_url=url,
        budget_usd=settings.run_budget_usd,
        status=RunStatus.ANALYZING,
        status_detail=READING_SITE,
    )
    session.add(run)
    session.flush()
    queue.enqueue(session, ANALYZE_SITE, {"run_id": str(run.id)}, run_after=now, dedupe_key=f"{ANALYZE_SITE}:{run.id}")
    return run
