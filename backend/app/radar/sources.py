"""The paid searches, through treg (treg.to), each with a dollar cap:

- LinkedIn's public job search, then each likely role's full posting (HarvestAPI, paid per page and per posting),
- company job boards found through Google (Serper), then read from the board itself (free) for the real details,
- LinkedIn posts where someone says they're hiring a GTM engineer (the poster is often the hiring manager).
"""

import math
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.radar import boards
from app.radar.fit import AGENCY, CANADA, RadarConfig, fits, flags_for, is_overseas, salary_in, title_score
from app.treg import Caller, TregError

LINKEDIN_JOBS = "harvestapi.linkedin.search.jobs"  # 25 jobs a page
JOBS_PAGE = 25
JOB_DETAILS = "harvestapi.linkedin.job.get"  # one posting, with its description
GOOGLE_SEARCH = "serper.web.search"  # 10 results a page
POST_SEARCH = "harvestapi.linkedin.post.search"  # 50 posts a page
# treg's list prices, the most one call can cost: each call is sent with its price as its ceiling.
CALL_USD = {LINKEDIN_JOBS: 0.001, JOB_DETAILS: 0.001, GOOGLE_SEARCH: 0.001, POST_SEARCH: 0.004}
ATS_CAP_USD = 0.05
POSTS_CAP_USD = 0.05
SNIPPET = 700
POST_TEXT = 1500
DAY_S = 86400
OVERLAP_DAYS = 0.125  # three hours of overlap with the last run
MAX_WINDOW_DAYS = 7
ATS_SITES = [
    "jobs.ashbyhq.com",
    "job-boards.greenhouse.io",
    "boards.greenhouse.io",
    "jobs.lever.co",
    "apply.workable.com",
]
ATS_LINK = [
    ("ashby", r"jobs\.ashbyhq\.com/([^/?#]+)/([0-9a-f-]{36})"),
    ("greenhouse", r"greenhouse\.io/([^/?#]+)/jobs/(\d+)"),
    ("lever", r"jobs\.lever\.co/([^/?#]+)/([0-9a-f-]{36})"),
    ("workable", r"apply\.workable\.com/([^/?#]+)/j/([0-9A-Za-z]+)"),
]
POST_QUERIES = [
    '"GTM hiring"',
    'hiring "GTM engineer"',
    'hiring "go-to-market engineer"',
    '"founding GTM engineer"',
    '"looking for a GTM engineer"',
    'hiring "GTM engineering"',
]
HIRING = re.compile(
    r"we(?:'|’)?re hiring|we are hiring|is hiring|now hiring|i(?:'|’)?m hiring|am hiring"
    r"|hiring (?:a|an|our|for|my|the)\b|looking for (?:a|an|our|the)\b[^.\n]{0,60}(?:gtm|go[- ]to[- ]market)"
    r"|join (?:us|our team)|open role|#hiring|first (?:gtm|go[- ]to[- ]market) (?:engineer|hire)"
    r"|apply (?:here|now|below)|link in (?:the )?comments|dm me",
    re.IGNORECASE,
)
POST_ROLE = re.compile(r"(?:gtm|go[- ]to[- ]market)\s+(?:engineer|engineering)", re.IGNORECASE)
SEEKING = re.compile(
    r"open to work|#opentowork|i(?:'|’)?m (?:looking|searching) for (?:my|a new|new)"
    r"|seeking (?:my|a new) (?:next )?role|my next role|laid off",
    re.IGNORECASE,
)
ANNOUNCE = re.compile(
    r"(?:joins|joined|joining) (?:us|the team|as)|welcome (?:to the team|aboard)"
    r"|excited to (?:share|announce) (?:that )?i\b|new role as|started a new position",
    re.IGNORECASE,
)
RECRUITER = re.compile(r"recruit|talent|staffing|headhunt|sourcer|job board|jobs in|remote work", re.IGNORECASE)


@dataclass
class Found:
    jobs: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    error: str = ""  # why the search stopped early; what it found and spent before that is still here


@dataclass
class Spend:
    """Calls charged against one search's cap. A call is made only when its whole list price still fits."""

    treg: Caller
    cap: float
    spent: float = 0.0

    def affords(self, tool: str) -> bool:
        return self.spent + CALL_USD[tool] <= self.cap + 1e-9

    def call(self, tool: str, *, query: dict[str, Any] | None = None, body: dict[str, Any] | None = None) -> Any:
        try:
            answer = self.treg.call(tool, query=query, body=body, max_usd=CALL_USD[tool])
        except TregError as e:
            self.spent += e.spent
            raise
        self.spent += answer.cost_usd
        return answer.body


def _elements(body: Any) -> list[dict[str, Any]]:
    items = body.get("elements") if isinstance(body, dict) else None
    return [i for i in items or [] if isinstance(i, dict)]


def window_seconds(days_since_last_good_run: float | None) -> int:
    """Search back to the last good run plus a little overlap: at least a day, at most a week."""
    days = 1.0 if days_since_last_good_run is None else days_since_last_good_run + OVERLAP_DAYS
    return int(min(MAX_WINDOW_DAYS, max(1.0, days)) * DAY_S)


# ----------------------------------------------------------------------------- LinkedIn jobs


def search_params(cfg: RadarConfig, since_seconds: int) -> list[dict[str, str]]:
    """One LinkedIn job search per keyword and location. LinkedIn's date filter is coarse (a day or a week), so the
    exact window is applied to the results afterwards."""
    posted = "24h" if since_seconds <= DAY_S else "week"
    searches = []
    for keyword in cfg.keywords:
        for location in cfg.locations:
            if keyword.strip() and location.strip():  # quoted, so LinkedIn matches the phrase
                params = {
                    "search": f'"{keyword.strip()}"',
                    "location": location.strip(),
                    "postedLimit": posted,
                    "sortBy": "date",
                }
                if cfg.toronto_ok and not CANADA.search(location):
                    params["workplaceType"] = "remote"  # US searches: remote roles only; Canadian roles can be on-site
                searches.append(params)
    return searches


def _text(value: Any) -> str:
    """A field as text: a list is joined, and LinkedIn's {"name": ...} entries (industries, say) give their name."""
    if isinstance(value, list):
        return ", ".join(t for t in (_text(v) for v in value) if t)
    if isinstance(value, dict):
        return str(value.get("name") or value.get("title") or "")
    return str(value or "")


def _location(listed: Any, full: dict[str, Any]) -> str:
    """Where the job is, as LinkedIn says it, with how it's worked when that isn't already in the text: the full
    posting says "United States" where the search said "United States (Remote)"."""
    text = str(listed.get("linkedinText") or "") if isinstance(listed, dict) else str(listed or "")
    place = full.get("location")
    if not text and isinstance(place, dict):
        text = str(place.get("linkedinText") or "")
    how = {"remote": "Remote", "hybrid": "Hybrid", "office": "On-site", "on-site": "On-site", "onsite": "On-site"}
    kind = how.get(str(full.get("workplaceType") or "").lower())
    if kind and kind.lower() not in text.lower():
        text = f"{text} ({kind})" if text else kind
    return text


def _salary(value: Any) -> str:
    if isinstance(value, dict):
        if value.get("text"):
            return str(value["text"])
        low, high = value.get("min"), value.get("max")
        if low or high:
            money = "–".join(f"{n:,.0f}" if isinstance(n, int | float) else str(n) for n in (low, high) if n)
            return f"{value.get('currency') or ''} {money}".strip()
        return ""
    return str(value or "")


def parse_job(item: dict[str, Any], details: dict[str, Any] | None = None) -> dict[str, Any]:
    """A job from LinkedIn's search results, completed by its full posting when that was read."""
    full = {**item, **(details or {})}
    job_id = str(full.get("id") or "")
    title = str(full.get("title") or "").strip()
    description = str(full.get("descriptionText") or "")
    company = {**(item.get("company") or {}), **((details or {}).get("company") or {})}
    location_text = _location(item.get("location"), full)
    apply = full.get("applyMethod") or {}
    return {
        "id": f"li-{job_id}",
        "job_id": job_id,
        "title": title,
        "company": str(company.get("name") or full.get("companyName") or "").strip(),
        "company_linkedin": str(company.get("linkedinUrl") or full.get("companyLink") or "").split("?")[0],
        "website": str(company.get("website") or ""),
        "employees": str(company.get("employeeCount") or ""),
        "industry": _text(full.get("industries") or company.get("industries")),
        "location": location_text,
        "posted": str(full.get("postedDate") or "")[:10],
        "applicants": str(full.get("applicants") or ""),
        "salary": _salary(full.get("salary")) or salary_in(description),
        "seniority": _text(full.get("experienceLevel")),
        "url": f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else str(full.get("url") or "").split("?")[0],
        "apply_url": str(
            (apply.get("companyApplyUrl") if isinstance(apply, dict) else "") or full.get("easyApplyUrl") or ""
        ),
        "fit": title_score(title),
        "flags": flags_for(location_text, description),
        "snippet": re.sub(r"\s+", " ", description)[:SNIPPET],
    }


def likely(job: dict[str, Any], cfg: RadarConfig) -> bool:
    """Worth reading the full posting: a GTM title at a company that isn't a staffing agency."""
    return (
        job["fit"] >= cfg.min_fit and bool(job["company"]) and not AGENCY.search(f"{job['company']} {job['industry']}")
    )


def filter_jobs(jobs: list[dict[str, Any]], cfg: RadarConfig) -> list[dict[str, Any]]:
    """GTM titles, no staffing agencies, roles that fit."""
    return [j for j in jobs if likely(j, cfg) and fits(j, cfg)[0]]


def _posted_since(item: dict[str, Any], since: datetime) -> bool:
    try:
        posted = datetime.fromisoformat(str(item.get("postedDate") or "").replace("Z", "+00:00"))
    except ValueError:
        return True  # no readable date: keep it, the fit rules decide
    return (posted if posted.tzinfo else posted.replace(tzinfo=UTC)) >= since


def posting(spend: Spend, job_id: str) -> dict[str, Any] | None:
    """A job's full posting, or None when the cap is reached or it can't be read: taken down since the search, or
    treg busy twice in a row. One posting failing never fails the search."""
    for attempt in range(2):
        if not spend.affords(JOB_DETAILS):
            return None
        try:
            body = spend.call(JOB_DETAILS, query={"jobId": job_id})
        except TregError as e:
            if e.retryable and attempt == 0:
                continue
            return None
        details = body.get("element") if isinstance(body, dict) else None
        return details if isinstance(details, dict) else None
    return None


def _listings(
    spend: Spend, cfg: RadarConfig, searches: list[dict[str, str]], since: datetime
) -> tuple[dict[str, dict[str, Any]], int, str]:
    """Each search's jobs posted in the window, at most `per_search` a search, as far as the cap goes. A failed call
    ends the searching but keeps what the calls before it found (they were paid for), with the reason."""
    listed: dict[str, dict[str, Any]] = {}
    scanned = 0
    for params in searches:
        taken = 0
        for page in range(1, math.ceil(cfg.per_search / JOBS_PAGE) + 1):
            if not spend.affords(LINKEDIN_JOBS):
                break
            try:
                items = _elements(spend.call(LINKEDIN_JOBS, query={**params, "page": str(page)}))
            except TregError as e:
                return listed, scanned, str(e)
            full = len(items) == JOBS_PAGE
            items = items[: cfg.per_search - taken]
            taken += len(items)
            scanned += len(items)
            for item in items:
                if item.get("id") and _posted_since(item, since):
                    listed.setdefault(str(item["id"]), item)
            if not full:
                break
    return listed, scanned, ""


def search_linkedin(treg: Caller, cfg: RadarConfig, since_seconds: int, now: datetime | None = None) -> Found:
    """Search LinkedIn, then read the full posting of each likely role (its description, pay and how to apply), as
    many as the daily cap covers. A role whose posting couldn't be read is judged on the search result alone."""
    spend = Spend(treg, cfg.daily_usd)
    since = (now or datetime.now(UTC)) - timedelta(seconds=since_seconds)
    searches = search_params(cfg, since_seconds)
    listed, scanned, error = _listings(spend, cfg, searches, since)
    jobs, unread = [], 0
    for job_id, item in listed.items():
        job = parse_job(item)
        if not likely(job, cfg):
            continue
        details = posting(spend, job_id)
        if details is None:
            unread += 1
        else:
            job = parse_job(item, details)
        jobs.append(job)
    kept = filter_jobs(jobs, cfg)
    meta = {"searches": len(searches), "scanned": scanned, "kept": len(kept), "spent_usd": round(spend.spent, 3)}
    if unread:
        meta["unread"] = unread
    return Found(kept, meta, error)


# ----------------------------------------------------------------------------- company job boards through Google


def ats_queries(cfg: RadarConfig) -> list[str]:
    return [f'site:{site} "{k.strip()}"' for site in ATS_SITES for k in cfg.keywords[:3] if k.strip()]


def search_ats(treg: Caller, web: boards.Http, cfg: RadarConfig, days: int, today: date) -> Found:
    """Roles posted straight to company job boards: these often never reach LinkedIn, so fewer people apply."""
    spend = Spend(treg, ATS_CAP_USD)
    recent = "qdr:d" if days <= 1 else f"qdr:d{days}"
    hits: list[str] = []
    error = ""
    for query in ats_queries(cfg):
        if not spend.affords(GOOGLE_SEARCH):
            break
        try:
            body = spend.call(GOOGLE_SEARCH, body={"q": query, "tbs": recent, "gl": "us", "hl": "en"})
        except TregError as e:  # the boards already found are still read
            error = str(e)
            break
        organic = body.get("organic") if isinstance(body, dict) else None
        hits += [str(hit.get("link") or "") for hit in organic or [] if isinstance(hit, dict)]
    wanted: dict[tuple[str, str], set[str]] = {}
    for url in hits:
        for ats, rx in ATS_LINK:
            if m := re.search(rx, url, re.IGNORECASE):
                wanted.setdefault((ats, m.group(1)), set()).add(m.group(2).lower())
                break
    found = []
    for (ats, slug), ids in wanted.items():
        got = boards.read(web, ats, slug)
        if not got:
            continue
        board_name, postings = got
        for j in postings:
            if not any(i in (j.get("url") or "").lower() for i in ids):
                continue
            text = re.sub(r"<[^>]+>", " ", j.get("text") or "")
            job_id = (j.get("url") or "").rstrip("/").split("/")[-1]
            found.append(
                {
                    "id": f"ats-{slug}-{job_id}"[:80],
                    "job_id": job_id,
                    "title": j["title"],
                    "company": board_name or slug.replace("-", " ").title(),
                    "company_linkedin": "",
                    "website": "",
                    "employees": "",
                    "industry": "",
                    "location": j.get("location") or "",
                    "posted": (j.get("posted") or "")[:10],
                    "applicants": "",
                    "salary": j.get("salary") or salary_in(text),
                    "seniority": "",
                    "url": j.get("url") or "",
                    "apply_url": j.get("url") or "",
                    "fit": title_score(j["title"]),
                    "flags": flags_for(j.get("location") or "", text),
                    "source": f"{ats} board",
                    "board": {"ats": ats, "slug": slug},
                    "snippet": re.sub(r"\s+", " ", text)[:SNIPPET],
                }
            )
    oldest = (today - timedelta(days=cfg.recent_days)).isoformat()
    kept = [
        j
        for j in found
        if j["fit"] >= cfg.min_fit
        and not is_overseas(j)
        and (not j["posted"] or j["posted"] >= oldest)
        and fits(j, cfg)[0]
    ]
    meta = {"boards": len(wanted), "read": len(found), "kept": len(kept), "charged_usd": round(spend.spent, 3)}
    return Found(kept, meta, error)


# ----------------------------------------------------------------------------- "we're hiring" posts


def hiring_post(post: dict[str, Any]) -> dict[str, Any] | None:
    """A post where someone says they're hiring a GTM engineer; None for job seekers, hire announcements and
    opinion posts."""
    text = post.get("content") or ""
    if not (HIRING.search(text) and POST_ROLE.search(text)) or SEEKING.search(text) or ANNOUNCE.search(text):
        return None
    author = post.get("author") or {}
    headline = author.get("info") or ""
    return {
        "id": str(post.get("id") or ""),
        "url": post.get("linkedinUrl") or "",
        "posted": ((post.get("postedAt") or {}).get("date") or "")[:10],
        "author": author.get("name") or "",
        "author_url": (author.get("linkedinUrl") or "").split("?")[0],
        "headline": headline[:200],
        "recruiter": bool(RECRUITER.search(f"{headline} {author.get('name') or ''}")),
        "text": re.sub(r"\s+", " ", text)[:POST_TEXT],
    }


def search_posts(treg: Caller, window: str) -> Found:
    spend = Spend(treg, POSTS_CAP_USD)
    kept: dict[str, dict[str, Any]] = {}
    scanned = 0
    error = ""
    for query in POST_QUERIES:
        if not spend.affords(POST_SEARCH):
            break
        try:
            body = spend.call(
                POST_SEARCH, query={"search": query, "postedLimit": window, "sortBy": "date", "page": "1"}
            )
        except TregError as e:  # the posts already read are kept
            error = str(e)
            break
        posts = _elements(body)
        scanned += len(posts)
        for post in posts:
            if (h := hiring_post(post)) and h["id"]:
                kept.setdefault(h["id"], h)
    meta = {"scanned": scanned, "kept": len(kept), "window": window, "charged_usd": round(spend.spent, 3)}
    return Found(list(kept.values()), meta, error)
