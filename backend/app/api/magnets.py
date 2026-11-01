"""Lead magnets: build one for a company in the background, follow it, and share the finished report by a private link.

The report link carries the magnet's id and an unguessable token; it's the only route here that needs no sign-in,
and it shows the report and nothing else.
"""

import hmac
import logging
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import exists, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.auth import AppSettings, DbSession, SignedIn
from app.clock import Today
from app.config import Settings
from app.db import session_factory
from app.enrich.apollo import ApolloError
from app.magnet.brain import BrainError
from app.magnet.build import BuildError, Spec, Tools, build, default_tools
from app.magnet.linkedin import LinkedInError
from app.magnet.site import SiteError
from app.models import Company, Magnet
from app.radar.apify import ApifyError
from app.radar.fit import domain_of
from app.schemas import (
    MagnetCreate,
    MagnetOut,
    MagnetSummary,
    PublicCompetitor,
    PublicIcp,
    PublicLead,
    PublicMagnet,
)
from app.services.history import record

log = logging.getLogger("gtm_tracker.magnets")

router = APIRouter(prefix="/api", tags=["magnets"], dependencies=[SignedIn])
public = APIRouter(prefix="/api/public", tags=["magnets"])

KIND = "engagement"
LIST_LIMIT = 20
TEASER_SHOWN = 5
STALE_AFTER = timedelta(minutes=30)  # a build reports every step and every post; this quiet, it died with the app
STOPPED = "The build stopped before it finished (the app restarted). Build it again."
KNOWN_ERRORS = (BuildError, BrainError, SiteError, LinkedInError, ApolloError, ApifyError)


class CancelledError(Exception):
    """The magnet was deleted, or given up on as stopped, while it was building."""


@dataclass
class Runtime:
    """How the API starts a build: in a background thread, with the real network. Tests run it inline with fakes."""

    tools: Callable[[], Tools]
    spawn: Callable[[Callable[[], None]], None]
    factory: sessionmaker[Session]


def _thread(work: Callable[[], None]) -> None:
    threading.Thread(target=work, daemon=True).start()


def get_runtime(request: Request, settings: AppSettings) -> Runtime:
    runtime = getattr(request.app.state, "magnet_runtime", None)
    return runtime or Runtime(tools=lambda: default_tools(settings), spawn=_thread, factory=session_factory())


MagnetRuntime = Annotated[Runtime, Depends(get_runtime)]


def missing_setup(settings: Settings, mode: str) -> str | None:
    """What has to be set up before a build can run, in words, or None."""
    for value, name in (
        (settings.anthropic_api_key, "ANTHROPIC_API_KEY"),
        (settings.apify_token, "APIFY_TOKEN"),
        (settings.apollo_api_key, "APOLLO_API_KEY"),
    ):
        if value is None or not value.get_secret_value():
            return f"Add {name} in the tracker's Railway variables first."
    if mode == "full" and settings.open_access:
        return "Turn on sign-in before building with emails."
    return None


def _now() -> datetime:
    return datetime.now(UTC)


def _stale(m: Magnet) -> bool:
    updated = m.updated_at or m.created_at
    return m.status == "running" and updated is not None and updated < _now() - STALE_AFTER


def _out(m: Magnet) -> MagnetOut:
    d = m.data or {}
    stale = _stale(m)
    report = d.get("report") if m.status == "ready" else None
    summary = None
    if isinstance(report, dict):
        stats = report.get("stats") or {}
        tiers = stats.get("tiers") or {}
        summary = MagnetSummary(
            leads=len(report.get("leads") or []),
            hot=int(tiers.get("hot", 0)),
            warm=int(tiers.get("warm", 0)),
            touch=int(tiers.get("touch", 0)),
            emails=int((stats.get("emails") or {}).get("found", 0)),
            fit=int(stats.get("fit", 0)),
            people=int(stats.get("people", 0)),
            apify_usd=float(stats.get("apify_usd", 0)),
        )
    token = d.get("token")
    return MagnetOut(
        id=m.id,
        company_id=m.company_id,
        kind=m.kind,
        status="failed" if stale else m.status,
        title=m.title,
        mode=str(d.get("mode") or ""),
        website=str(d.get("website") or ""),
        step="" if stale else str(d.get("step") or ""),
        error=STOPPED if stale or (m.status == "failed" and not d.get("error")) else str(d.get("error") or ""),
        created=m.created_at,
        link=f"/m/{m.id}/{token}" if summary and isinstance(token, str) else None,
        views=int(d.get("views", 0)),
        summary=summary,
    )


def _company(session: Session, company_id: str, *, lock: bool = False) -> Company:
    company = session.get(Company, company_id, with_for_update=lock)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That company isn't in the tracker.")
    return company


@router.get("/companies/{company_id}/magnets")
def list_for_company(company_id: str, session: DbSession) -> list[MagnetOut]:
    _company(session, company_id)
    rows = session.scalars(
        select(Magnet)
        .where(Magnet.company_id == company_id)
        .order_by(Magnet.created_at.desc(), Magnet.id)
        .limit(LIST_LIMIT)
    ).all()
    return [_out(m) for m in rows]


@router.post("/companies/{company_id}/magnets", status_code=status.HTTP_202_ACCEPTED)
def start(
    company_id: str, body: MagnetCreate, session: DbSession, settings: AppSettings, today: Today, runtime: MagnetRuntime
) -> MagnetOut:
    """Start building, in the background. The magnet shows each step; one build per company at a time (the company
    row stays locked until the new magnet is saved, so two quick clicks can't both start one)."""
    company = _company(session, company_id, lock=True)
    problem = missing_setup(settings, body.mode)
    if problem:
        raise HTTPException(status.HTTP_409_CONFLICT, problem)
    website = (body.website or company.website or company.domain or "").strip()
    if not website:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Add the company's website first.")
    running = (Magnet.company_id == company_id) & (Magnet.status == "running")
    cutoff = _now() - STALE_AFTER
    if session.scalar(select(exists().where(running, Magnet.updated_at >= cutoff))):
        raise HTTPException(status.HTTP_409_CONFLICT, "A lead magnet is already building for this company.")
    # any left behind by a restart stop counting as running; their workers, if still alive, stop at their next step
    session.execute(update(Magnet).where(running, Magnet.updated_at < cutoff).values(status="failed"))
    competitors = tuple(dict.fromkeys(d for d in (domain_of(c) for c in body.competitors) if d))
    magnet = Magnet(
        company_id=company.id,
        kind=KIND,
        status="running",
        title=f"{company.name}: {'full list' if body.mode == 'full' else 'teaser'}"[:300],
        data={
            "mode": body.mode,
            "website": website,
            "competitors": list(competitors),
            "step": "starting",
            "token": secrets.token_urlsafe(32),
        },
    )
    session.add(magnet)
    session.commit()
    spec = Spec(mode=body.mode, company=company.name, website=website, competitors=competitors)
    magnet_id = magnet.id
    runtime.spawn(lambda: run(runtime, magnet_id, spec, today))
    return _out(magnet)


@router.get("/magnets/{magnet_id}")
def get_one(magnet_id: str, session: DbSession) -> MagnetOut:
    m = session.get(Magnet, magnet_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That lead magnet is gone.")
    return _out(m)


@router.delete("/magnets/{magnet_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(magnet_id: str, session: DbSession) -> Response:
    """Delete it, which also turns its link off."""
    m = session.get(Magnet, magnet_id)
    if m is not None:
        session.delete(m)
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@public.get("/magnets/{magnet_id}/{token}")
def report(magnet_id: str, token: str, session: DbSession) -> PublicMagnet:
    """The finished report, for whoever has the link. A teaser shows its first few leads."""
    m = session.get(Magnet, magnet_id)
    stored = (m.data or {}).get("token") if m else None
    if m is None or not isinstance(stored, str) or not hmac.compare_digest(stored.encode(), token.encode()):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This link doesn't work any more.")
    built = (m.data or {}).get("report")
    if m.status != "ready" or not isinstance(built, dict):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This report isn't ready yet.")
    m.data = {**m.data, "views": int(m.data.get("views", 0)) + 1, "last_viewed": _now().isoformat()}
    session.commit()
    return public_view(built)


def public_view(built: dict[str, Any]) -> PublicMagnet:
    leads = [_public_lead(lead) for lead in built.get("leads") or [] if isinstance(lead, dict)]
    shown = leads[:TEASER_SHOWN] if built.get("mode") == "teaser" else leads
    stats = built.get("stats") or {}
    icp = built.get("icp") or {}
    return PublicMagnet(
        company=str(built.get("company") or ""),
        mode=str(built.get("mode") or ""),
        built=str(built.get("built") or ""),
        icp=PublicIcp(
            sells=str(icp.get("sells") or ""),
            industries=_strings(icp.get("industries")),
            company_sizes=_strings(icp.get("company_sizes")),
            titles=_strings(icp.get("titles")),
            seniority=_strings(icp.get("seniority")),
            functions=_strings(icp.get("functions")),
        ),
        competitors=[
            PublicCompetitor(
                name=str(c.get("name") or ""),
                domain=str(c.get("domain") or ""),
                linkedin=str(c.get("linkedin") or ""),
                why=str(c.get("why") or ""),
            )
            for c in built.get("competitors") or []
            if isinstance(c, dict)
        ],
        leads=shown,
        fit=int(stats.get("fit", 0)),
        in_region=int(stats.get("in_region", len(leads))),
        more=len(leads) - len(shown),
    )


def _strings(value: Any) -> list[str]:
    return [str(v) for v in value if v] if isinstance(value, list) else []


def _public_lead(lead: dict[str, Any]) -> PublicLead:
    return PublicLead(
        name=str(lead.get("name") or ""),
        title=str(lead.get("title") or ""),
        company=str(lead.get("company") or ""),
        headline=str(lead.get("headline") or ""),
        linkedin=str(lead.get("linkedin") or ""),
        country=str(lead.get("country") or ""),
        tier=str(lead.get("tier") or "touch"),
        points=int(lead.get("points", 0)),
        touches=int(lead.get("touches", 0)),
        comments=int(lead.get("comments", 0)),
        reactions=int(lead.get("reactions", 0)),
        posts=int(lead.get("posts", 0)),
        competitors=_strings(lead.get("competitors")),
        last=str(lead["last"]) if lead.get("last") else None,
        said=_strings(lead.get("said")),
        why_fit=str(lead.get("why_fit") or ""),
        email=str(lead["email"]) if lead.get("email") else None,
    )


def run(runtime: Runtime, magnet_id: str, spec: Spec, today: date) -> None:
    """Build it and store the result. Each step is saved as it starts, so the page can show where it is."""

    def save(**changes: Any) -> bool:
        """Save progress or the result; False, saving nothing, once the magnet is no longer this build's to update
        (deleted, or given up on as stopped and maybe started again)."""
        with runtime.factory() as session:
            m = session.get(Magnet, magnet_id, with_for_update=True)
            if m is None or m.status != "running":
                return False
            data = {**m.data, **{k: v for k, v in changes.items() if k != "status"}}
            m.data = data
            if "status" in changes:
                m.status = changes["status"]
                if changes["status"] == "ready":
                    leads = len(data["report"]["leads"])
                    record(
                        session, "magnet", f"{spec.company}: lead magnet ready ({leads} leads)", company_id=m.company_id
                    )
            session.commit()
            return True

    def progress(step: str, _info: dict[str, Any]) -> None:
        if not save(step=step):
            raise CancelledError  # deleted or superseded: stop before spending more

    try:
        report_data = build(spec, runtime.tools(), today, progress)
    except CancelledError:
        return
    except KNOWN_ERRORS as e:
        save(status="failed", step="", error=str(e)[:500])
        return
    except Exception:  # anything else is a bug; the log has it, the page says so plainly
        log.exception("lead magnet build failed", extra={"magnet": magnet_id})
        save(status="failed", step="", error="Something went wrong while building. Try again.")
        return
    save(status="ready", step="", error="", report=report_data, finished_at=_now().isoformat())
