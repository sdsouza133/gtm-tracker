"""Lead magnets: build one for a company in the background, follow it, and share the finished report by a private link.

Two kinds: an engagement magnet (people in the ICP engaging with competitors) and a champion report (people who used
the product at a customer and just moved to a new company in the ICP).

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
from sqlalchemy import exists, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.auth import AppSettings, DbSession, SignedIn
from app.clock import Today
from app.config import Settings
from app.db import session_factory
from app.enrich.apollo import ApolloError
from app.magnet.brain import BrainError
from app.magnet.build import BuildError, Progress, Spec, Tools, build, default_tools
from app.magnet.champions import TREG_CAP_USD, ChampionSpec, ChampionTools, build_champions, champion_tools
from app.magnet.linkedin import LinkedInError
from app.magnet.site import SiteError
from app.models import Company, Magnet, Setting
from app.radar.fit import domain_of
from app.schemas import (
    ChampionCustomer,
    ChampionOut,
    ChampionRole,
    ChampionSkip,
    ChampionsReport,
    ChampionsSummary,
    ChampionWatch,
    MagnetCreate,
    MagnetOut,
    MagnetReport,
    MagnetStart,
    MagnetSummary,
    PublicCompetitor,
    PublicIcp,
    PublicLead,
    PublicMagnet,
)
from app.services.history import record
from app.treg import TregError

log = logging.getLogger("gtm_tracker.magnets")

router = APIRouter(prefix="/api", tags=["magnets"], dependencies=[SignedIn])
public = APIRouter(prefix="/api/public", tags=["magnets"])

KIND = "engagement"
CHAMPIONS = "champions"
LIST_LIMIT = 20
ALL_LIMIT = 50
UNLINKED_LOCK = "magnets:no-company"  # one build at a time for websites outside the tracker
CHAMPIONS_LOCK = "magnets:champions"  # one champion report at a time, whoever asks: each one is paid for
LEDGER = "magnet_spend:champions"  # {day, usd}: what today's champion reports have reserved
TEASER_SHOWN = 5
CHAMPIONS_SHOWN = 3  # the shared link names the top few champions and counts the rest
STALE_AFTER = timedelta(minutes=30)  # a build reports every step and every post; this quiet, it died with the app
STOPPED = "The build stopped before it finished (the app restarted). Build it again."
KNOWN_ERRORS = (BuildError, BrainError, SiteError, LinkedInError, ApolloError, TregError)


class CancelledError(Exception):
    """The magnet was deleted, or given up on as stopped, while it was building."""


@dataclass
class Runtime:
    """How the API starts a build: in a background thread, with the real network. Tests run it inline with fakes."""

    tools: Callable[[], Tools]
    spawn: Callable[[Callable[[], None]], None]
    factory: sessionmaker[Session]
    champions: Callable[[], ChampionTools] | None = None


def _thread(work: Callable[[], None]) -> None:
    threading.Thread(target=work, daemon=True).start()


def get_runtime(request: Request, settings: AppSettings) -> Runtime:
    runtime = getattr(request.app.state, "magnet_runtime", None)
    return runtime or Runtime(
        tools=lambda: default_tools(settings),
        spawn=_thread,
        factory=session_factory(),
        champions=lambda: champion_tools(settings),
    )


MagnetRuntime = Annotated[Runtime, Depends(get_runtime)]


def missing_setup(settings: Settings, mode: str, kind: str = KIND) -> str | None:
    """What has to be set up before a build can run, in words, or None. A champion report needs no Apollo, holds no
    emails, and so also runs without sign-in."""
    needed = [(settings.anthropic_api_key, "ANTHROPIC_API_KEY"), (settings.treg_token, "TREG_TOKEN")]
    if kind != CHAMPIONS:
        needed.append((settings.apollo_api_key, "APOLLO_API_KEY"))
    for value, name in needed:
        if value is None or not value.get_secret_value():
            return f"Add {name} in the tracker's Railway variables first."
    if kind != CHAMPIONS and mode == "full" and settings.open_access:
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
    champions = _champions_summary(report) if m.kind == CHAMPIONS and isinstance(report, dict) else None
    if isinstance(report, dict) and m.kind != CHAMPIONS:
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
            linkedin_usd=float(stats.get("linkedin_usd", stats.get("apify_usd", 0))),  # older builds: apify_usd
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
        domain=str(d.get("domain") or domain_of(str(d.get("website") or ""))),
        step="" if stale else str(d.get("step") or ""),
        error=STOPPED if stale or (m.status == "failed" and not d.get("error")) else str(d.get("error") or ""),
        created=m.created_at,
        link=f"/m/{m.id}/{token}" if (summary or champions) and isinstance(token, str) else None,
        views=int(d.get("views", 0)),
        summary=summary,
        champions=champions,
    )


def _champions_summary(report: dict[str, Any]) -> ChampionsSummary:
    stats = report.get("stats") or {}
    grades = stats.get("grades") or {}
    return ChampionsSummary(
        champions=int(stats.get("champions", 0)),
        a=int(grades.get("A", 0)),
        b=int(grades.get("B", 0)),
        c=int(grades.get("C", 0)),
        new=int(stats.get("new", 0)),
        repeat=bool(stats.get("repeat")),
        customers=int(stats.get("customers", 0)),
        matched=int(stats.get("matched", 0)),
        movers=int(stats.get("movers", 0)),
        watch=int(stats.get("watch", 0)),
        linkedin_usd=float(stats.get("linkedin_usd", 0)),
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


@router.get("/magnets")
def list_all(session: DbSession, kind: str | None = None, domain: str | None = None) -> list[MagnetOut]:
    """Every lead magnet, newest first: those built for a tracker company and those built for any website. `kind`
    and `domain` narrow it (a Fractional prospect's champion reports, say)."""
    query = select(Magnet)
    if kind:
        query = query.where(Magnet.kind == kind)
    if domain:
        query = query.where(Magnet.data["domain"].as_string() == domain_of(domain))
    rows = session.scalars(query.order_by(Magnet.created_at.desc(), Magnet.id).limit(ALL_LIMIT)).all()
    return [_out(m) for m in rows]


@router.post("/companies/{company_id}/magnets", status_code=status.HTTP_202_ACCEPTED)
def start(
    company_id: str, body: MagnetCreate, session: DbSession, settings: AppSettings, today: Today, runtime: MagnetRuntime
) -> MagnetOut:
    """Start building, in the background. The magnet shows each step; one build per company at a time (the company
    row stays locked until the new magnet is saved, so two quick clicks can't both start one)."""
    company = _company(session, company_id, lock=True)
    website = (body.website or company.website or company.domain or "").strip()
    if not website:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Add the company's website first.")
    if body.kind == CHAMPIONS:
        session.execute(select(func.pg_advisory_xact_lock(func.hashtext(CHAMPIONS_LOCK))))
    return _begin(session, settings, today, runtime, body, company=company, name=company.name, website=website)


@router.post("/magnets", status_code=status.HTTP_202_ACCEPTED)
def start_any(
    body: MagnetStart, session: DbSession, settings: AppSettings, today: Today, runtime: MagnetRuntime
) -> MagnetOut:
    """Start one for any website, without a company in the tracker. One such build at a time (a lock held until the
    new magnet is saved, so two quick clicks can't both start one)."""
    website = body.website.strip()
    host = domain_of(website)
    if "." not in host or any(ch.isspace() for ch in host):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Type the company's website, like acme.com.")
    lock = CHAMPIONS_LOCK if body.kind == CHAMPIONS else UNLINKED_LOCK
    session.execute(select(func.pg_advisory_xact_lock(func.hashtext(lock))))
    name = (body.name or "").strip() or host
    return _begin(session, settings, today, runtime, body, company=None, name=name, website=website)


def _begin(
    session: Session,
    settings: Settings,
    today: date,
    runtime: Runtime,
    body: MagnetCreate | MagnetStart,
    *,
    company: Company | None,
    name: str,
    website: str,
) -> MagnetOut:
    """Save the new magnet as running and start its build. The caller holds the lock that makes this the only one."""
    problem = missing_setup(settings, body.mode, body.kind)
    if problem:
        raise HTTPException(status.HTTP_409_CONFLICT, problem)
    if body.kind == CHAMPIONS:
        return _begin_champions(session, settings, today, runtime, company=company, name=name, website=website)
    owner = Magnet.company_id == company.id if company else Magnet.company_id.is_(None)
    running = owner & (Magnet.kind != CHAMPIONS) & (Magnet.status == "running")
    cutoff = _now() - STALE_AFTER
    if session.scalar(select(exists().where(running, Magnet.updated_at >= cutoff))):
        busy = "for this company" if company else "for a website outside the tracker"
        raise HTTPException(status.HTTP_409_CONFLICT, f"A lead magnet is already building {busy}.")
    # any left behind by a restart stop counting as running; their workers, if still alive, stop at their next step
    session.execute(update(Magnet).where(running, Magnet.updated_at < cutoff).values(status="failed"))
    competitors = tuple(dict.fromkeys(d for d in (domain_of(c) for c in body.competitors) if d))
    magnet = Magnet(
        company_id=company.id if company else None,
        kind=KIND,
        status="running",
        title=f"{name}: {'full list' if body.mode == 'full' else 'teaser'}"[:300],
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
    spec = Spec(mode=body.mode, company=name, website=website, competitors=competitors)
    magnet_id = magnet.id
    runtime.spawn(lambda: run(runtime, magnet_id, spec, today))
    return _out(magnet)


def _begin_champions(
    session: Session,
    settings: Settings,
    today: date,
    runtime: Runtime,
    *,
    company: Company | None,
    name: str,
    website: str,
) -> MagnetOut:
    """Save a new champion report as running and start it: one at a time across the app (the caller holds the lock),
    and only while today's reports have room under the daily limit. Its cap is reserved now and what it didn't spend
    is given back when it's done."""
    champions = runtime.champions
    if champions is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Champion reports aren't set up on this server.")
    running = (Magnet.kind == CHAMPIONS) & (Magnet.status == "running")
    cutoff = _now() - STALE_AFTER
    if session.scalar(select(exists().where(running, Magnet.updated_at >= cutoff))):
        raise HTTPException(status.HTTP_409_CONFLICT, "A champion report is already building. Try again in a minute.")
    session.execute(update(Magnet).where(running, Magnet.updated_at < cutoff).values(status="failed"))
    ledger = session.get(Setting, LEDGER, with_for_update=True)
    held = ledger.value if ledger is not None and isinstance(ledger.value, dict) else {}
    used = float(held.get("usd", 0)) if held.get("day") == today.isoformat() else 0.0
    cap = settings.magnet_champions_daily_usd
    if used + TREG_CAP_USD > cap + 1e-9:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Today's champion reports have used ${used:.2f} of the ${cap:.2f} daily limit. Try again tomorrow.",
        )
    reserved = {"day": today.isoformat(), "usd": round(used + TREG_CAP_USD, 4)}
    if ledger is None:
        session.add(Setting(key=LEDGER, value=reserved))
    else:
        ledger.value = reserved
    domain = domain_of(website)
    last = session.scalars(
        select(Magnet)
        .where(Magnet.kind == CHAMPIONS, Magnet.status == "ready", Magnet.data["domain"].as_string() == domain)
        .order_by(Magnet.created_at.desc(), Magnet.id)
        .limit(1)
    ).first()
    before = (last.data or {}).get("report") if last else None
    magnet = Magnet(
        company_id=company.id if company else None,
        kind=CHAMPIONS,
        status="running",
        title=f"{name}: champion report"[:300],
        data={
            "mode": "teaser",
            "website": website,
            "domain": domain,
            "step": "starting",
            "token": secrets.token_urlsafe(32),
            "reserved": TREG_CAP_USD,
            "day": today.isoformat(),
        },
    )
    session.add(magnet)
    session.commit()
    spec = ChampionSpec(company=name, website=website, before=before if isinstance(before, dict) else None)
    magnet_id = magnet.id
    runtime.spawn(lambda: run_champions(runtime, champions, magnet_id, spec, today))
    return _out(magnet)


@router.get("/magnets/{magnet_id}")
def get_one(magnet_id: str, session: DbSession) -> MagnetOut:
    m = session.get(Magnet, magnet_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That lead magnet is gone.")
    return _out(m)


@router.get("/magnets/{magnet_id}/report")
def full_report(magnet_id: str, session: DbSession) -> MagnetReport:
    """The whole finished report, for the signed-in owner: every lead or champion, and for a champion report the
    watch list and everyone ruled out, with why."""
    m = session.get(Magnet, magnet_id)
    built = (m.data or {}).get("report") if m else None
    if m is None or m.status != "ready" or not isinstance(built, dict):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That report isn't ready.")
    if m.kind == CHAMPIONS:
        return champions_view(built, full=True)
    return public_view(built, full=True)


@router.delete("/magnets/{magnet_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(magnet_id: str, session: DbSession) -> Response:
    """Delete it, which also turns its link off."""
    m = session.get(Magnet, magnet_id)
    if m is not None:
        session.delete(m)
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@public.get("/magnets/{magnet_id}/{token}")
def report(magnet_id: str, token: str, session: DbSession) -> MagnetReport:
    """The finished report, for whoever has the link. A teaser shows its first few leads. The row is locked while the
    view is counted, so two people opening it at once both count."""
    m = session.get(Magnet, magnet_id, with_for_update=True)
    stored = (m.data or {}).get("token") if m else None
    if m is None or not isinstance(stored, str) or not hmac.compare_digest(stored.encode(), token.encode()):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This link doesn't work any more.")
    built = (m.data or {}).get("report")
    if m.status != "ready" or not isinstance(built, dict):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This report isn't ready yet.")
    # only the count changes: updated_at is set to itself, so the row's onupdate timestamp doesn't move either
    views = int(m.data.get("views", 0)) + 1
    session.execute(
        update(Magnet)
        .where(Magnet.id == m.id)
        .values(data={**m.data, "views": views}, updated_at=Magnet.updated_at)
        .execution_options(synchronize_session=False)
    )
    session.commit()
    if m.kind == CHAMPIONS:
        return champions_view(built, full=False)
    return public_view(built)


def _public_icp(icp: Any) -> PublicIcp:
    icp = icp if isinstance(icp, dict) else {}
    return PublicIcp(
        sells=str(icp.get("sells") or ""),
        industries=_strings(icp.get("industries")),
        company_sizes=_strings(icp.get("company_sizes")),
        titles=_strings(icp.get("titles")),
        seniority=_strings(icp.get("seniority")),
        functions=_strings(icp.get("functions")),
    )


def public_view(built: dict[str, Any], *, full: bool = False) -> PublicMagnet:
    """An engagement magnet as its link shows it: a teaser's first few leads, unless `full` (the owner's view)."""
    leads = [_public_lead(lead) for lead in built.get("leads") or [] if isinstance(lead, dict)]
    shown = leads[:TEASER_SHOWN] if built.get("mode") == "teaser" and not full else leads
    stats = built.get("stats") or {}
    return PublicMagnet(
        kind="engagement",
        company=str(built.get("company") or ""),
        mode=str(built.get("mode") or ""),
        built=str(built.get("built") or ""),
        icp=_public_icp(built.get("icp")),
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


def champions_view(built: dict[str, Any], *, full: bool) -> ChampionsReport:
    """A champion report as its link shows it (the top few champions, the rest counted), or in `full` for the owner:
    every champion, the watch list, everyone ruled out and what it cost."""
    champions = [_champion(c) for c in built.get("champions") or [] if isinstance(c, dict)]
    shown = champions if full else champions[:CHAMPIONS_SHOWN]
    stats = built.get("stats") or {}
    raw_skipped = built.get("skipped")
    skipped: dict[str, Any] = raw_skipped if isinstance(raw_skipped, dict) else {}
    return ChampionsReport(
        kind="champions",
        company=str(built.get("company") or ""),
        website=str(built.get("website") or ""),
        built=str(built.get("built") or ""),
        icp=_public_icp(built.get("icp")),
        customers=[
            ChampionCustomer(
                name=str(c.get("name") or ""),
                domain=str(c.get("domain") or ""),
                evidence=str(c.get("evidence") or ""),
                linkedin=str(c.get("linkedin") or ""),
                linkedin_name=str(c.get("linkedin_name") or ""),
                industry=str(c.get("industry") or ""),
            )
            for c in built.get("customers") or []
            if isinstance(c, dict)
        ],
        champions=shown,
        more=len(champions) - len(shown),
        movers=int(stats.get("movers", 0)),
        repeat=bool(stats.get("repeat")),
        skipped={str(k): int(v) for k, v in skipped.items() if isinstance(v, int)},
        watch=[_watch(w) for w in built.get("watch") or [] if isinstance(w, dict)] if full else [],
        skipped_people=[
            ChampionSkip(
                name=str(p.get("name") or ""),
                linkedin=str(p.get("linkedin") or ""),
                now=str(p.get("now") or ""),
                reason=str(p.get("reason") or ""),
            )
            for p in built.get("skipped_people") or []
            if isinstance(p, dict)
        ]
        if full
        else [],
        linkedin_usd=float(stats.get("linkedin_usd", 0)) if full else 0.0,
    )


def _role(value: Any) -> ChampionRole:
    r = value if isinstance(value, dict) else {}
    return ChampionRole(
        title=str(r.get("title") or ""),
        company=str(r.get("company") or ""),
        company_linkedin=str(r.get("company_linkedin") or ""),
        industry=str(r.get("industry") or ""),
        start=str(r["start"]) if r.get("start") else None,
        end=str(r["end"]) if r.get("end") else None,
        months=int(r.get("months") or 0),
    )


def _champion(c: dict[str, Any]) -> ChampionOut:
    grade = str(c.get("grade") or "C")
    return ChampionOut(
        name=str(c.get("name") or ""),
        linkedin=str(c.get("linkedin") or ""),
        location=str(c.get("location") or ""),
        grade="A" if grade == "A" else "B" if grade == "B" else "C",
        new=bool(c.get("new")),
        was=_role(c.get("was")),
        now=_role(c.get("now")),
        why=str(c.get("why") or ""),
    )


def _watch(w: dict[str, Any]) -> ChampionWatch:
    status_ = str(w.get("status") or "unchecked")
    return ChampionWatch(
        name=str(w.get("name") or ""),
        title=str(w.get("title") or ""),
        company=str(w.get("company") or ""),
        linkedin=str(w.get("linkedin") or ""),
        status="still_there"
        if status_ == "still_there"
        else "moved"
        if status_ == "moved"
        else "not_found"
        if status_ == "not_found"
        else "unchecked",
        now=str(w.get("now") or ""),
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
    """Build an engagement magnet and store the result."""
    _run(
        runtime,
        magnet_id,
        lambda progress: build(spec, runtime.tools(), today, progress),
        lambda report: f"{spec.company}: lead magnet ready ({len(report['leads'])} leads)",
    )


def run_champions(
    runtime: Runtime, tools: Callable[[], ChampionTools], magnet_id: str, spec: ChampionSpec, today: date
) -> None:
    """Build a champion report and store the result; what it didn't spend of its reservation goes back to the day."""
    _run(
        runtime,
        magnet_id,
        lambda progress: build_champions(spec, tools(), today, progress),
        lambda report: f"{spec.company}: champion report ready ({len(report['champions'])} champions)",
        settle=True,
    )


def _run(
    runtime: Runtime,
    magnet_id: str,
    work: Callable[[Progress], dict[str, Any]],
    ready: Callable[[dict[str, Any]], str],
    *,
    settle: bool = False,
) -> None:
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
                    record(session, "magnet", ready(data["report"]), company_id=m.company_id)
                    if settle:
                        _give_back(session, data)
            session.commit()
            return True

    def progress(step: str, _info: dict[str, Any]) -> None:
        if not save(step=step):
            raise CancelledError  # deleted or superseded: stop before spending more

    try:
        report_data = work(progress)
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


def _give_back(session: Session, data: dict[str, Any]) -> None:
    """Return the part of a finished report's reservation it didn't spend to the day's ledger. A build that failed
    or was deleted keeps its whole reservation: what it spent isn't known."""
    spent = float(((data.get("report") or {}).get("stats") or {}).get("linkedin_usd", 0))
    unused = max(0.0, float(data.get("reserved", 0)) - spent)
    ledger = session.get(Setting, LEDGER, with_for_update=True)
    held = ledger.value if ledger is not None and isinstance(ledger.value, dict) else None
    if ledger is None or held is None or held.get("day") != data.get("day") or not unused:
        return
    ledger.value = {**held, "usd": round(max(0.0, float(held.get("usd", 0)) - unused), 4)}
