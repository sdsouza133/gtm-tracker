"""One radar pass, and the morning schedule.

A pass reads the network first (job boards, then the paid searches) with no database transaction open, then applies
everything in one transaction:

- a new fitting posting on a tracked company's board becomes an Apply move for today, and brings the company back if
  it was parked for a stale or misfit role;
- a posting gone from the board puts a warning on its open Apply move;
- a LinkedIn or board-search role at a tracked company becomes an Apply move; any other role lands in the inbox;
- companies whose role has gone stale (older than `recent_days`, nothing done yet) are parked;
- hiring posts are kept for two weeks for the daily research to qualify.

A Postgres advisory lock makes sure only one pass runs at a time, across every copy of the app.
"""

import logging
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import Connection, Engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.models import Company, Move, MoveStatus, MoveType, ParkedWhy, RadarItem, Setting, Stage
from app.radar import boards, sources
from app.radar.apify import Apify
from app.radar.fit import RadarConfig, domain_of, fits, is_overseas, linkedin_slug, norm, web_url
from app.services.history import record

log = logging.getLogger("gtm_tracker.radar")

LOCK_KEY = 7_204_311  # any constant; identifies "the radar" among advisory locks
SKIP_STAGES = frozenset({Stage.BENCH, Stage.REJECTED, Stage.PARKED, Stage.OFFER})  # not re-checked each morning
FULL_SEARCH_DAYS = 7  # a company with no known board gets a full board search this often
BOARD_WORKERS = 8
INBOX_DAYS = 45
POSTS_DAYS = 14
POSTS_KEEP = 300
MAX_ATTEMPTS = 3
STARTING_GRACE = timedelta(minutes=2)  # a pass asked for this recently counts as running before it takes the lock
CHECK_EVERY_S = 300
APPLY_WHY_BOARD = (
    "New posting on their job board, found by the job radar on {day}. "
    "Apply today, then email the hiring manager and say you've applied."
)
APPLY_WHY_LINKEDIN = (
    "Posted {posted}, found by the job radar. Apply today, then email the hiring manager and say you've applied."
)


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if isinstance(value, str) and value else None
    except ValueError:
        return None


def is_running(session: Session, status: dict[str, Any]) -> bool:
    """A pass holds the lock, or one was asked for moments ago and is still starting. A flag left behind by a crash
    or a deploy mid-pass doesn't count, so it can't block "Check now" until the next morning."""
    if not status.get("running"):
        return False
    held = session.scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND granted AND classid = 0 "
            "AND objid = :k AND objsubid = 1 AND database = (SELECT oid FROM pg_database "
            "WHERE datname = current_database()))"
        ),
        {"k": LOCK_KEY},
    )
    if held:
        return True
    try:
        since = datetime.now(UTC) - datetime.fromisoformat(status.get("started_at") or "")
    except ValueError:
        return False
    return since < STARTING_GRACE


def get_setting(session: Session, key: str, default: Any) -> Any:
    row = session.get(Setting, key)
    return row.value if row is not None and row.value is not None else default


def put_setting(session: Session, key: str, value: Any) -> None:
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value


def config(session: Session) -> RadarConfig:
    return RadarConfig.from_setting(get_setting(session, "radar_config", {}))


def _days_since(iso: str | None, now: datetime) -> float | None:
    if not iso:
        return None
    try:
        at = datetime.fromisoformat(iso)
    except ValueError:
        return None
    return (now - (at if at.tzinfo else at.replace(tzinfo=UTC))).total_seconds() / 86400


# ----------------------------------------------------------------------------- roles and their age


def job_date(c: Company) -> str:
    """When the company's best current role was posted ("" when there's no role)."""
    postings = [
        p
        for p in ((c.research.get("jobs") or {}).get("postings") or [])
        if p.get("fit", 0) >= 2 and not is_overseas({"location": p.get("location"), "flags": []})  # noqa: PLR2004
    ]
    best = ""
    if postings:
        top = max(p.get("fit", 0) for p in postings)
        best = max((p.get("posted") or "" for p in postings if p.get("fit", 0) == top), default="")
    fallback = c.posted.isoformat() if c.posted else ""
    return max(best or fallback, c.research.get("relisted") or "")


def role_age(c: Company, today: date) -> int | None:
    day = job_date(c)[:10]
    try:
        return (today - date.fromisoformat(day)).days if day else None
    except ValueError:
        return None


def started(session: Session, company_id: str) -> bool:
    """Anything done there: a move finished or skipped, or a reach-out with a step ticked (n/a included)."""
    for kind, status, seq in session.execute(
        select(Move.type, Move.status, Move.sequence).where(Move.company_id == company_id)
    ):
        if status is not MoveStatus.OPEN or (kind is MoveType.REACH and any((seq or {}).get("steps", {}).values())):
            return True
    return False


def park_stale_roles(session: Session, today: date, recent_days: int) -> list[str]:
    parked = []
    for c in session.scalars(select(Company).where(Company.stage == Stage.NOT_STARTED)):
        age = role_age(c, today)
        if age is None or age <= recent_days or started(session, c.id):
            continue
        c.stage = Stage.PARKED
        c.parked_why = ParkedWhy.STALE_ROLE
        c.parked_reason = (
            f"Role posted {job_date(c)[:10]} ({age} days ago). Only roles from the last {recent_days} days are worked; "
            "it comes back if they post a new one."
        )
        parked.append(f"{c.name} ({age}d)")
    if parked:
        record(
            session,
            "stage",
            f"Parked {len(parked)} companies whose role is over {recent_days} days old: {', '.join(parked)}",
        )
    return parked


def _unpark(session: Session, c: Company, why: str) -> None:
    c.stage = Stage.NOT_STARTED
    c.parked_why = None
    c.parked_reason = None
    record(session, "stage", f"{c.name}: back from parked, {why}", company_id=c.id)


def apply_if_new(session: Session, c: Company, title: str, url: str, today: date, why: str) -> bool:
    """An Apply move for today, unless one is open for the company or this role was handled before (same link, or the
    same title: reposts get new links)."""
    t, url = norm(title), web_url(url)
    for m in session.scalars(select(Move).where(Move.company_id == c.id, Move.type == MoveType.APPLY)):
        if m.status is MoveStatus.OPEN or m.url == url or norm(m.title.removeprefix("Apply: ")) == t:
            return False
    session.add(
        Move(company_id=c.id, type=MoveType.APPLY, title=f"Apply: {title}"[:500], due=today, notes=why, url=url or None)
    )
    return True


# ----------------------------------------------------------------------------- boards of tracked companies


@dataclass
class BoardCheck:
    jobs: dict[str, Any]
    new: list[dict[str, Any]]
    closed: list[dict[str, Any]]


def check_board(web: boards.Http, c: dict[str, Any], today: date, min_fit: int, now: datetime) -> BoardCheck | None:
    """Re-check one company's board; None when it isn't due for a check."""
    prev = c["jobs"]
    board = prev.get("board")
    finder = boards.find_jobs
    if board:
        res = finder(web, c["name"], c["domain"], c["job_url"], c["open_role"], board=board)
        if not res.board:  # the board moved or is down: search again from scratch
            res = finder(web, c["name"], c["domain"], c["job_url"], c["open_role"])
    elif (_days_since(prev.get("checked_at"), now) or 1e9) >= FULL_SEARCH_DAYS:
        res = finder(web, c["name"], c["domain"], c["job_url"], c["open_role"])
    else:
        return None
    prev_posts = prev.get("postings") or []
    seen = list(prev.get("seen") or [p["url"] for p in prev_posts])
    first_seen = {p["url"]: p.get("first_seen", "") for p in prev_posts}
    current = {p["url"] for p in res.postings}
    new = [p for p in res.postings if p["url"] not in set(seen) and p["fit"] >= min_fit and prev]
    same_board = bool(board and res.board) and (board["ats"], board["slug"].lower()) == (
        res.board["ats"],  # type: ignore[index]
        res.board["slug"].lower(),  # type: ignore[index]
    )
    # only the board's own postings can close; a LinkedIn posting added from the radar was never on it
    closed = [p for p in prev_posts if same_board and p["url"] not in current and "linkedin.com/" not in p["url"]]
    return BoardCheck(res.as_jobs(seen, first_seen, today), new, closed)


def check_boards(web: boards.Http, companies: list[dict[str, Any]], today: date, min_fit: int) -> dict[str, BoardCheck]:
    now = datetime.now(UTC)
    out: dict[str, BoardCheck] = {}
    with ThreadPoolExecutor(max_workers=BOARD_WORKERS) as pool:
        futures = {c["id"]: pool.submit(check_board, web, c, today, min_fit, now) for c in companies}
        for cid, future in futures.items():
            try:
                result = future.result()
            except Exception:  # one bad board never stops the run
                log.warning("board check failed", extra={"company_id": cid}, exc_info=True)
                continue
            if result:
                out[cid] = result
    return out


# ----------------------------------------------------------------------------- one pass


@dataclass
class Searches:
    linkedin: sources.Found = field(default_factory=sources.Found)
    ats: sources.Found = field(default_factory=sources.Found)
    posts: sources.Found = field(default_factory=sources.Found)
    errors: list[str] = field(default_factory=list)


def search_all(
    apify: sources.Runner, web: boards.Http, cfg: RadarConfig, status: dict[str, Any], today: date
) -> Searches:
    now = datetime.now(UTC)
    out = Searches()
    window = sources.window_seconds(_days_since(status.get("last_linkedin_at"), now))
    try:
        out.linkedin = sources.search_linkedin(apify, cfg, window)
    except Exception as e:
        out.errors.append(f"LinkedIn search failed: {e}"[:300])
    if cfg.ats_search:
        try:
            out.ats = sources.search_ats(apify, web, cfg, max(1, round(window / 86400)), today)
        except Exception as e:
            out.errors.append(f"Job-board search failed: {e}"[:300])
    if cfg.post_search:
        last_posts = _days_since(status.get("last_posts_at"), now)
        try:
            out.posts = sources.search_posts(apify, "24h" if last_posts is not None and last_posts <= 1.25 else "week")  # noqa: PLR2004
        except Exception as e:
            out.errors.append(f"Hiring-post search failed: {e}"[:300])
    return out


def _company_snapshot(c: Company) -> dict[str, Any]:
    return {
        "id": c.id,
        "name": c.name,
        "domain": c.domain or domain_of(c.website or ""),
        "job_url": c.job_url or "",
        "open_role": c.open_role or "",
        "jobs": c.research.get("jobs") or {},
    }


BOARD_SLUG = Company.research["jobs"]["board"]["slug"].as_string()


def _job_keys(job: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        ("l", linkedin_slug(job.get("company_linkedin") or "")),
        ("d", domain_of(job.get("website") or "")),
        ("n", norm(job.get("company") or "")),
        ("b", ((job.get("board") or {}).get("slug") or "").lower()),
    ]


class Index:
    """Finds the tracked company behind a job: by LinkedIn page, domain, name, or job-board slug. Built once per pass
    from the few columns it needs, not whole rows."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.keys: dict[tuple[str, str], str] = {}
        rows = session.execute(
            select(Company.id, Company.linkedin, Company.domain, Company.website, Company.name, BOARD_SLUG)
        )
        for cid, linkedin, domain, website, name, slug in rows:
            for key in (
                ("l", linkedin_slug(linkedin or "")),
                ("d", domain or domain_of(website or "")),
                ("n", norm(name)),
                ("b", (slug or "").lower()),
            ):
                if key[1]:
                    self.keys.setdefault(key, cid)

    def match(self, job: dict[str, Any]) -> Company | None:
        cid = next((self.keys[k] for k in _job_keys(job) if k[1] and k in self.keys), None)
        return self.session.get(Company, cid) if cid else None


def find_company(session: Session, job: dict[str, Any]) -> Company | None:
    """The same match as `Index`, for one job, with a few indexed lookups instead of reading every company."""
    for kind, value in _job_keys(job):
        if not value:
            continue
        if kind == "l":
            rows = session.scalars(select(Company).where(Company.linkedin.ilike(f"%/company/{value}%")).limit(5))
            hit = next((c for c in rows if linkedin_slug(c.linkedin or "") == value), None)
        elif kind == "d":
            hit = company_with_domain(session, value)
        elif kind == "n":
            squashed = func.regexp_replace(func.lower(Company.name), "[^a-z0-9]", "", "g")
            hit = session.scalars(select(Company).where(squashed == value).limit(1)).first()
        else:
            hit = session.scalars(select(Company).where(func.lower(BOARD_SLUG) == value).limit(1)).first()
        if hit is not None:
            return hit
    return None


def company_with_domain(session: Session, domain: str) -> Company | None:
    by_column = session.scalars(select(Company).where(func.lower(Company.domain) == domain).limit(1)).first()
    if by_column is not None:
        return by_column
    rows = session.scalars(
        select(Company).where(Company.domain.is_(None), Company.website.ilike(f"%{domain}%")).limit(20)
    )
    return next((c for c in rows if domain_of(c.website or "") == domain), None)


def _apply_board_checks(
    session: Session, cfg: RadarConfig, checks: dict[str, BoardCheck], today: date, summary: dict[str, Any]
) -> None:
    for cid, check in checks.items():
        c = session.get(Company, cid)
        if c is None:
            continue
        c.research = {**c.research, "jobs": check.jobs}
        fitting = [p for p in check.new if fits(p, cfg)[0]]
        if fitting and c.stage is Stage.PARKED and c.parked_why in (ParkedWhy.STALE_ROLE, ParkedWhy.NOT_A_FIT):
            _unpark(session, c, "they posted a new role")
        for p in check.new:
            summary["tracked_new"] += 1
            ok, why_not = fits(p, cfg)
            why = APPLY_WHY_BOARD.format(day=today.isoformat())
            moved = (
                ok
                and c.stage not in (Stage.PARKED, Stage.REJECTED)
                and apply_if_new(session, c, p["title"], p["url"], today, why)
            )
            summary["moves_added"] += int(moved)
            tail = " (Apply move added for today)" if moved else (f" (skipped: {why_not})" if not ok else "")
            record(session, "radar", f"{c.name}: new role on their job board: {p['title']}{tail}", company_id=c.id)
        for p in check.closed:
            summary["closed"] += 1
            record(session, "radar", f"{c.name}: posting closed: {p['title']}", company_id=c.id)
            for move in session.scalars(
                select(Move).where(Move.company_id == c.id, Move.type == MoveType.APPLY, Move.status == MoveStatus.OPEN)
            ):
                if move.url == p["url"] and "was gone from their job board" not in move.notes:
                    warning = f"This posting was gone from their job board on {today}. Check it's still open."
                    move.notes = f"{warning} {move.notes}".strip()


def _apply_found_jobs(session: Session, found: Searches, today: date, summary: dict[str, Any]) -> None:
    index = Index(session)
    have = set(session.scalars(select(RadarItem.id)))
    linkedin_urls = {x["url"] for x in found.linkedin.jobs}
    for j in found.linkedin.jobs + [j for j in found.ats.jobs if j["url"] not in linkedin_urls]:
        c = index.match(j)
        if c and c.stage is Stage.PARKED and c.parked_why in (ParkedWhy.STALE_ROLE, ParkedWhy.NOT_A_FIT):
            relisted = max(c.research.get("relisted") or "", (j.get("posted") or today.isoformat())[:10])
            c.research = {**c.research, "relisted": relisted}
            _unpark(session, c, f"they re-listed a role: {j['title']}")
        if c and c.stage in (Stage.REJECTED, Stage.PARKED):
            continue
        if c and c.stage is not Stage.BENCH:
            why = APPLY_WHY_LINKEDIN.format(posted=f"on {j['posted']}" if j.get("posted") else "recently")
            if apply_if_new(session, c, j["title"], j["url"], today, why):
                summary["linkedin_tracked"] += 1
                summary["moves_added"] += 1
                record(session, "radar", f"{c.name}: new role on LinkedIn: {j['title']}", company_id=c.id)
            continue
        item_id = j["id"][:80]
        if item_id in have:
            continue
        have.add(item_id)
        session.add(
            RadarItem(
                id=item_id,
                company=(j["company"] or "")[:200],
                title=(j["title"] or "")[:300],
                url=web_url(j["url"]),
                posted=_day(j.get("posted")),
                fit=j["fit"],
                state="new",
                company_id=c.id if c else None,
                data={k: v for k, v in j.items() if k not in ("id", "company", "title", "url", "posted", "fit")}
                | {"found_at": datetime.now(UTC).isoformat(), "on_bench": bool(c)},
            )
        )
        summary["inbox_new"] += 1


def _keep_posts(session: Session, found: Searches, summary: dict[str, Any]) -> None:
    if not found.posts.meta:
        return
    now = datetime.now(UTC)
    kept = {
        p["id"]: p
        for p in get_setting(session, "radar_posts", [])
        if (_days_since(p.get("found_at"), now) or 0) <= POSTS_DAYS
    }
    fresh = [dict(p, found_at=now.isoformat()) for p in found.posts.jobs if p["id"] not in kept]
    put_setting(session, "radar_posts", (fresh + list(kept.values()))[:POSTS_KEEP])
    summary.update(posts_scanned=found.posts.meta["scanned"], posts_new=len(fresh))


def apply_results(
    session: Session, cfg: RadarConfig, checks: dict[str, BoardCheck], found: Searches, today: date
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "boards_checked": len(checks),
        "tracked_new": 0,
        "moves_added": 0,
        "closed": 0,
        "inbox_new": 0,
        "linkedin_tracked": 0,
    }
    _apply_board_checks(session, cfg, checks, today, summary)
    session.flush()
    _apply_found_jobs(session, found, today, summary)
    park_stale_roles(session, today, cfg.recent_days)
    cutoff = datetime.now(UTC) - timedelta(days=INBOX_DAYS)
    for item in session.scalars(select(RadarItem).where(RadarItem.created_at < cutoff)):
        session.delete(item)
    _keep_posts(session, found, summary)
    if meta := found.linkedin.meta:
        summary.update(linkedin_searches=meta["searches"], linkedin_scanned=meta["scanned"], linkedin_kept=meta["kept"])
    if meta := found.ats.meta:
        summary.update(ats_boards=meta["boards"], ats_kept=meta["kept"])
    summary["spent_usd"] = round(
        float(found.linkedin.meta.get("spent_usd", 0))
        + float(found.ats.meta.get("charged_usd", 0))
        + float(found.posts.meta.get("charged_usd", 0)),
        2,
    )
    return summary


def describe(summary: dict[str, Any], errors: list[str]) -> str:
    bits = [
        f"{summary['tracked_new'] + summary['linkedin_tracked']} new role(s) at your companies",
        f"{summary['inbox_new']} new in the inbox",
    ]
    if "linkedin_scanned" in summary:
        bits.append(f"LinkedIn: {summary['linkedin_kept']} GTM roles out of {summary['linkedin_scanned']} scanned")
    if "ats_boards" in summary:
        bits.append(f"company job boards: {summary['ats_kept']} GTM roles on {summary['ats_boards']} boards")
    if "posts_scanned" in summary:
        bits.append(f"hiring posts: {summary['posts_new']} new out of {summary['posts_scanned']} scanned")
    return "Job radar: " + ", ".join(bits) + (f". {' '.join(errors)}" if errors else "")


@dataclass
class Tools:
    """What a pass talks to; tests swap in fakes."""

    web: boards.Http
    apify: sources.Runner | None


@contextmanager
def pass_lock(factory: sessionmaker[Session]) -> Iterator[bool]:
    """Take the advisory lock for one pass; yields whether it was free. The lock belongs to a database connection, so
    one connection holds it for the whole pass and unlocks it: a session would hand its connection back to the pool
    at each commit. That connection autocommits, so no transaction stays open while the pass runs."""
    bind = factory.kw.get("bind")
    if isinstance(bind, Connection):  # tests: every session shares one connection already
        held: AbstractContextManager[Connection] = nullcontext(bind)
    elif isinstance(bind, Engine):
        held = bind.connect().execution_options(isolation_level="AUTOCOMMIT")
    else:
        raise TypeError("the radar needs a session factory bound to an engine")
    with held as conn:
        got = bool(conn.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}))
        try:
            yield got
        finally:
            if got:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})


def run_once(factory: sessionmaker[Session], settings: Settings, tools: Tools, trigger: str) -> bool:
    """One full pass. Returns False when another pass holds the lock."""
    with pass_lock(factory) as got:
        if got:
            _run(factory, settings, tools, trigger)
    return got


def _run(factory: sessionmaker[Session], settings: Settings, tools: Tools, trigger: str) -> None:
    today = datetime.now(settings.tz).date()
    started_at = datetime.now(UTC).isoformat()
    with factory() as session:
        status = dict(get_setting(session, "radar_status", {}))
        attempts = dict(status.get("attempts") or {})
        attempts = {today.isoformat(): attempts.get(today.isoformat(), 0) + 1}
        status.update(
            running=True,
            started_at=started_at,
            trigger=trigger,
            step="checking job boards",
            error="",
            attempts=attempts,
        )
        put_setting(session, "radar_status", status)
        session.commit()
    try:
        with factory() as session:
            cfg = config(session)
            tracked = [
                _company_snapshot(c)
                for c in session.scalars(
                    select(Company).where(
                        Company.stage.not_in(SKIP_STAGES) | (Company.parked_why == ParkedWhy.STALE_ROLE)
                    )
                )
            ]
        checks = check_boards(tools.web, tracked, today, cfg.min_fit)
        found = search_all(tools.apify, tools.web, cfg, status, today) if tools.apify else Searches()
        with factory() as session:
            summary = apply_results(session, cfg, checks, found, today)
            status = dict(get_setting(session, "radar_status", {}))
            status.update(
                running=False,
                step="",
                last_run_at=datetime.now(UTC).isoformat(),
                last_run_date=today.isoformat(),
                summary=summary,
                error=" ".join(found.errors),
            )
            if tools.apify and not found.errors:
                status["last_linkedin_at"] = started_at
            if found.posts.meta:
                status["last_posts_at"] = started_at
            put_setting(session, "radar_status", status)
            record(session, "radar", describe(summary, found.errors))
            session.commit()
    except Exception as e:
        log.exception("radar pass failed")
        with factory() as session:
            status = dict(get_setting(session, "radar_status", {}))
            status.update(
                running=False,
                step="",
                error=f"{type(e).__name__}: {e}"[:400],
                last_run_at=datetime.now(UTC).isoformat(),
            )
            if attempts.get(today.isoformat(), 0) >= MAX_ATTEMPTS:
                status["last_run_date"] = today.isoformat()  # stop retrying until tomorrow
            put_setting(session, "radar_status", status)
            session.commit()


# ----------------------------------------------------------------------------- the morning schedule


def due(session: Session, settings: Settings) -> bool:
    now = datetime.now(settings.tz)
    status = get_setting(session, "radar_status", {})
    return now.hour >= config(session).hour and status.get("last_run_date") != now.date().isoformat()


def start_scheduler(
    factory: sessionmaker[Session], settings: Settings, make_tools: Callable[[], Tools]
) -> threading.Event:
    """Checks every five minutes; runs once a day after the configured hour. Returns an event that stops it."""
    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(CHECK_EVERY_S):
            try:
                with factory() as session:
                    is_due = due(session, settings)
                if is_due:
                    run_once(factory, settings, make_tools(), "schedule")
            except Exception:
                log.exception("radar scheduler check failed")

    threading.Thread(target=loop, name="job-radar", daemon=True).start()
    return stop


def default_tools(settings: Settings) -> Tools:
    token = settings.apify_token.get_secret_value() if settings.apify_token else ""
    return Tools(web=boards.Web(), apify=Apify(token) if token else None)


def find_board_for(
    factory: sessionmaker[Session], web: boards.Http, company_id: str, title: str, move_id: str, today: date
) -> None:
    """After a radar role is added for a new company: find its own job board, so the Apply move can point at the
    direct posting instead of LinkedIn."""
    with factory() as session:
        c = session.get(Company, company_id)
        if c is None:
            return
        name, domain, job_url = c.name, c.domain or domain_of(c.website or ""), c.job_url or ""
    found = boards.find_jobs(web, name, domain, job_url, title)
    if not found.board:
        return
    with factory() as session:
        c = session.get(Company, company_id)
        if c is None:
            return
        earlier = (c.research.get("jobs") or {}).get("postings") or []
        known = {p["url"] for p in found.postings}
        found.postings += [p for p in earlier if p["url"] not in known]
        first_seen = {p["url"]: p.get("first_seen", "") for p in earlier}
        c.research = {**c.research, "jobs": found.as_jobs([p["url"] for p in earlier], first_seen, today)}
        t = norm(title)
        direct = next(
            (
                p
                for p in found.postings
                if "linkedin.com" not in p["url"] and t and (norm(p["title"]) in t or t in norm(p["title"]))
            ),
            None,
        )
        move = session.get(Move, move_id)
        if direct and move is not None and move.status is MoveStatus.OPEN:
            move.url = web_url(direct["url"]) or move.url
            move.notes = f"Direct link on their {found.board['ats'].title()} board. {move.notes}".strip()
        record(session, "research", f"{c.name}: job board found ({found.board['ats']})", company_id=c.id)
        session.commit()
