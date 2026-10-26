"""Getting a company ready to reach: a work email for each person still in play, and what the company does."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.enrich.apollo import ApolloError, Finder, work_email
from app.models import Company, Person
from app.services.history import record


@dataclass(frozen=True)
class Enriched:
    tried: int  # people looked up this time
    found: int  # of them, how many now have an email
    about: bool  # whether "what they do" was filled in


def to_look_up(person: Person) -> bool:
    """Still in play, no email yet, not tried yet, and something to find them by: a LinkedIn profile or the company's
    domain. A name alone isn't sent to Apollo or marked tried, so adding either later lets them be looked up."""
    findable = bool(person.linkedin or person.company.domain)
    return findable and not (person.left or person.email or person.details.get("apollo_tried"))


def about_missing(company: Company) -> bool:
    research = company.research or {}
    return bool(company.domain) and not research.get("pmf_reason") and not research.get("apollo_tried")


def needs_lookup(company: Company) -> bool:
    """Someone at the company still to look up, or "what they do" still to fill in."""
    return about_missing(company) or any(to_look_up(p) for p in company.people)


def enrich_company(session: Session, company: Company, apollo: Finder, today: date) -> Enriched:
    """Look each person up once (a miss isn't retried every time the company opens), and the company if research left
    "what they do" blank."""
    tried = found = 0
    for person in company.people:
        if not to_look_up(person):
            continue
        try:
            hit = apollo.match(name=person.name, domain=company.domain, linkedin=person.linkedin)
        except ApolloError:
            break  # Apollo is down or out of credits: stop, and try the rest another time
        tried += 1
        email = work_email(hit)
        session.refresh(person, with_for_update=True)  # an email typed in during the lookup wins
        details = {**person.details, "apollo_tried": today.isoformat()}
        if email and not person.email:
            person.email = email
            details |= {"email_source": "apollo", "email_status": str((hit or {}).get("email_status") or "")}
            found += 1
        person.details = details

    about = False
    if company.domain and about_missing(company):
        try:
            org = apollo.organization(company.domain) or {}
        except ApolloError:
            org = None
        session.refresh(company, ["research"], with_for_update=True)  # research edited during the lookup wins
        if org is not None and about_missing(company):
            text = str(org.get("short_description") or "").strip()
            company.research = {
                **(company.research or {}),
                "apollo_tried": today.isoformat(),
                "apollo_about": text[:1500],
            }
            about = bool(text)

    if found:
        record(session, "research", f"Apollo found {found} of {tried} emails at {company.name}", company_id=company.id)
    return Enriched(tried=tried, found=found, about=about)
