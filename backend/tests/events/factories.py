"""Small builders for test data. Synthetic values only."""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.events.models import Run, RunStatus


def make_run(
    session: Session,
    *,
    budget_usd: Decimal = Decimal("3.00"),
    domain: str = "acme.example",
    status: RunStatus = RunStatus.ANALYZING,
    website_url: str | None = None,
    company_id: str | None = None,
) -> Run:
    run = Run(
        company_id=company_id,
        domain=domain,
        website_url=website_url or f"https://{domain}/",
        budget_usd=budget_usd,
        status=status,
    )
    session.add(run)
    session.flush()
    return run
