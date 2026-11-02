"""The whole pipeline after approval, on the offline fakes: every step hands over to the next, and it ends with the
run's list."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.events.config import EventsSettings
from app.events.models import Job, JobStatus, Lead, Run, RunStatus
from app.events.pipeline.base import JobContext
from app.events.pipeline.collect import approve
from app.events.pipeline.jobs import JOBS
from app.events.providers.fakes import FakeLlm
from app.events.providers.registry import build_providers
from app.events.providers.types import FetchedPage
from app.events.schemas import ApprovedEvent
from app.events.worker import Worker
from tests.events.factories import make_run

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def test_an_approved_run_ends_with_its_list(db: Session) -> None:
    home = FetchedPage("https://acme.example/", 200, "Acme Analytics | Home", None, "")
    run = make_run(db, status=RunStatus.AWAITING_APPROVAL)
    run.icp = FakeLlm().analyze_site([home]).value.model_dump(mode="json")
    summit = ApprovedEvent.model_validate(
        {"name": "Pipeline Summit", "queries": ['"Pipeline Summit"', "#PipelineSummit"]}
    )
    assert approve(db, run.id, [summit], now=NOW)
    db.commit()

    clock, settings = Clock(), EventsSettings()
    providers = build_providers(settings)
    w = Worker(JobContext(settings=settings, providers=providers, clock=clock), JOBS, name="worker-a")
    for _ in range(200):
        if w.run_once():
            continue
        db.expire_all()
        due = db.scalar(select(func.min(Job.run_after)).where(Job.status == JobStatus.QUEUED))
        if due is None:
            break
        clock.now = max(clock.now, due)  # a search to poll again, or the next turn of a job
    else:
        raise AssertionError("jobs are still waiting")

    db.expire_all()
    ready = db.get(Run, run.id)
    assert ready is not None
    assert (ready.status, ready.error) == (RunStatus.READY, None)
    listed = list(db.scalars(select(Lead).where(Lead.run_id == run.id, Lead.included)))
    assert 0 < len(listed) == ready.leads_count <= settings.max_leads
    assert all(lead.icp_score >= settings.min_icp_score and lead.icp_reasons for lead in listed)
    assert {job.status for job in db.scalars(select(Job))} == {JobStatus.DONE}
