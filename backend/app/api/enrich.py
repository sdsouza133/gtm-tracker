"""Apollo: verified work emails (and what a company does), a company at a time or for everything on Today, and
LinkedIn profile links with verified emails for everyone on the board and the Fractional list who lacks them."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.companies import get_company
from app.auth import AppSettings, DbSession, SignedIn
from app.clock import Today
from app.enrich.apollo import Apollo, Finder
from app.models import Company
from app.schemas import ContactsOut, EnrichOut
from app.services import contacts
from app.services import today as today_service
from app.services.enrich import enrich_company, needs_lookup

router = APIRouter(prefix="/api", tags=["enrich"], dependencies=[SignedIn])

TODAY_COMPANIES = 10  # at most this many companies a call, so one call stays quick
CONTACTS_PER_CALL = 100  # people a call asks Apollo about, at most: ten requests, so one call stays well under a minute


def _apollo(settings: AppSettings) -> Apollo:
    """Apollo, with or without sign-in: the owner asked for verified emails always (Nov 24). With OPEN_ACCESS on,
    anyone with the tracker's address can see them."""
    key = settings.apollo_api_key.get_secret_value() if settings.apollo_api_key else ""
    if not key:
        raise HTTPException(status.HTTP_409_CONFLICT, "Apollo isn't set up (APOLLO_API_KEY).")
    return Apollo(key)


def get_finder(settings: AppSettings) -> Finder:
    return _apollo(settings)


def get_contact_finder(settings: AppSettings) -> contacts.ContactFinder:
    return _apollo(settings)


ApolloFinder = Annotated[Finder, Depends(get_finder)]
ContactApollo = Annotated[contacts.ContactFinder, Depends(get_contact_finder)]


@router.post("/companies/{company_id}/enrich")
def enrich_one(company_id: str, session: DbSession, today: Today, apollo: ApolloFinder) -> EnrichOut:
    """Find verified work emails for this company's people, and what it does if research left that blank."""
    done = enrich_company(session, get_company(session, company_id), apollo, today)
    session.commit()
    return EnrichOut(tried=done.tried, found=done.found, companies=1)


@router.post("/enrich/today")
def enrich_today(session: DbSession, settings: AppSettings, today: Today, apollo: ApolloFinder) -> EnrichOut:
    """Get the companies on Today ready before they're opened. A company counts toward the batch while someone there is
    still to look up, or while "what they do" is blank and Apollo hasn't been asked about the company yet. So each call
    reaches further down the list, and once everything has been tried it costs nothing."""
    built = today_service.build(session, settings, today)
    ids = list(dict.fromkeys(m.company_id for _, moves in built.groups for m in moves if m.company_id))
    # everyone at those companies in one query, not one per company
    loaded = session.scalars(select(Company).where(Company.id.in_(ids)).options(selectinload(Company.people))).all()
    by_id = {c.id: c for c in loaded}
    todo = [by_id[i] for i in ids if i in by_id and needs_lookup(by_id[i])]
    tried = found = 0
    for c in todo[:TODAY_COMPANIES]:
        done = enrich_company(session, c, apollo, today)
        tried, found = tried + done.tried, found + done.found
        session.commit()
    return EnrichOut(tried=tried, found=found, companies=min(len(todo), TODAY_COMPANIES))


@router.post("/people/contacts")
def find_contacts(session: DbSession, today: Today, apollo: ContactApollo) -> ContactsOut:
    """LinkedIn profile links and verified work emails for people on the board and the Fractional list who lack
    either, up to 100 people a call. Each person is asked about once; only the link and a verified email at their
    company's domain are kept. Call again while `left` is above zero; once everyone has been asked, a call costs
    nothing."""
    done = contacts.fill(session, apollo, today, CONTACTS_PER_CALL)
    session.commit()
    return ContactsOut(tried=done.tried, links=done.links, emails=done.emails, left=done.left)
