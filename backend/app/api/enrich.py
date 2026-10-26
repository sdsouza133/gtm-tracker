"""Finding work emails (and what a company does) with Apollo, a company at a time or for everything on Today."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.companies import get_company
from app.auth import AppSettings, DbSession, SignedIn
from app.clock import Today
from app.enrich.apollo import Apollo, Finder
from app.models import Company
from app.schemas import EnrichOut
from app.services import today as today_service
from app.services.enrich import enrich_company, needs_lookup

router = APIRouter(prefix="/api", tags=["enrich"], dependencies=[SignedIn])

TODAY_COMPANIES = 10  # at most this many companies a call, so one call stays quick


def get_finder(settings: AppSettings) -> Finder:
    """Apollo, once sign-in protects what it finds: emails never go into a tracker anyone can open."""
    if settings.open_access:
        raise HTTPException(status.HTTP_409_CONFLICT, "Turn on sign-in before finding emails.")
    key = settings.apollo_api_key.get_secret_value() if settings.apollo_api_key else ""
    if not key:
        raise HTTPException(status.HTTP_409_CONFLICT, "Apollo isn't set up (APOLLO_API_KEY).")
    return Apollo(key)


ApolloFinder = Annotated[Finder, Depends(get_finder)]


@router.post("/companies/{company_id}/enrich")
def enrich_one(company_id: str, session: DbSession, today: Today, apollo: ApolloFinder) -> EnrichOut:
    """Find work emails for this company's people, and what it does if research left that blank."""
    done = enrich_company(session, get_company(session, company_id), apollo, today)
    session.commit()
    return EnrichOut(tried=done.tried, found=done.found, companies=1)


@router.post("/enrich/today")
def enrich_today(session: DbSession, settings: AppSettings, today: Today, apollo: ApolloFinder) -> EnrichOut:
    """Get the companies on Today ready before they're opened. Only companies with someone not yet looked up count
    toward the batch, so each call reaches further down the list, and calling it again costs nothing."""
    built = today_service.build(session, settings, today)
    todo: list[Company] = []
    for _, moves in built.groups:
        for m in moves:
            c = m.company
            if c is not None and c not in todo and needs_lookup(c):
                todo.append(c)
    tried = found = 0
    for c in todo[:TODAY_COMPANIES]:
        done = enrich_company(session, c, apollo, today)
        tried, found = tried + done.tried, found + done.found
        session.commit()
    return EnrichOut(tried=tried, found=found, companies=min(len(todo), TODAY_COMPANIES))
