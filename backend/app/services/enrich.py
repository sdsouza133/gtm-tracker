"""Getting a company ready to reach: a work email for each person still in play, and what the company does."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.enrich.apollo import ApolloError, Finder, work_email
from app.models import Company
from app.services.history import record


@dataclass(frozen=True)
class Enriched:
    tried: int  # people looked up this time
    found: int  # of them, how many now have an email
    about: bool  # whether "what they do" was filled in


def enrich_company(session: Session, company: Company, apollo: Finder, today: date) -> Enriched:
    """Look each person up once (a miss isn't retried every time the company opens), and the company if research left
    "what they do" blank."""
    tried = found = 0
    for person in company.people:
        if person.left or person.email or person.details.get("apollo_tried"):
            continue
        try:
            hit = apollo.match(name=person.name, domain=company.domain, linkedin=person.linkedin)
        except ApolloError:
            break  # Apollo is down or out of credits: stop, and try the rest another time
        tried += 1
        details = {**person.details, "apollo_tried": today.isoformat()}
        email = work_email(hit)
        if email:
            person.email = email
            details |= {"email_source": "apollo", "email_status": str((hit or {}).get("email_status") or "")}
            found += 1
        person.details = details

    about = False
    research = company.research or {}
    if company.domain and not research.get("pmf_reason") and not research.get("apollo_tried"):
        try:
            org = apollo.organization(company.domain) or {}
        except ApolloError:
            org = None
        if org is not None:
            text = str(org.get("short_description") or "").strip()
            company.research = {**research, "apollo_tried": today.isoformat(), "apollo_about": text[:1500]}
            about = bool(text)

    if found:
        record(session, "research", f"Apollo found {found} of {tried} emails at {company.name}", company_id=company.id)
    return Enriched(tried=tried, found=found, about=about)
