"""The paid searches, through Apify, each with a dollar cap:

- LinkedIn's public job search (pay per result),
- company job boards found through Google, then read from the board itself (free) for the real details,
- LinkedIn posts where someone says they're hiring a GTM engineer (the poster is often the hiring manager).
"""

import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Protocol

from app.radar import boards
from app.radar.apify import RunResult
from app.radar.fit import AGENCY, CANADA, RadarConfig, fits, flags_for, is_overseas, salary_in, title_score

LINKEDIN_JOBS = "curious_coder/linkedin-jobs-scraper"
PRICE_PER_JOB = 0.002
GOOGLE_SEARCH = "apify/google-search-scraper"
GOOGLE_CAP_USD = 0.50  # Apify's minimum cap for this actor
POST_SEARCH = "harvestapi/linkedin-post-search"
POSTS_CAP_USD = 0.40
POSTS_PER_QUERY = 50
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


class Runner(Protocol):
    def run(
        self, actor: str, actor_input: dict[str, Any], max_usd: float, *, partial_ok: bool = False
    ) -> RunResult: ...


@dataclass
class Found:
    jobs: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


def window_seconds(days_since_last_good_run: float | None) -> int:
    """Search back to the last good run plus a little overlap: at least a day, at most a week."""
    days = 1.0 if days_since_last_good_run is None else days_since_last_good_run + OVERLAP_DAYS
    return int(min(MAX_WINDOW_DAYS, max(1.0, days)) * DAY_S)


# ----------------------------------------------------------------------------- LinkedIn jobs


def search_urls(cfg: RadarConfig, since_seconds: int) -> list[str]:
    urls = []
    for keyword in cfg.keywords:
        for location in cfg.locations:
            if keyword.strip() and location.strip():  # quoted, so LinkedIn matches the phrase
                params = {
                    "keywords": f'"{keyword.strip()}"',
                    "location": location.strip(),
                    "f_TPR": f"r{since_seconds}",
                }
                if cfg.toronto_ok and not CANADA.search(location):
                    params["f_WT"] = "2"  # US searches: remote roles only; Canadian roles can be on-site
                urls.append(f"https://www.linkedin.com/jobs/search/?{urllib.parse.urlencode(params)}")
    return urls


def parse_job(item: dict[str, Any]) -> dict[str, Any]:
    job_id = str(item.get("id") or "")
    title = (item.get("title") or "").strip()
    description = item.get("descriptionText") or ""
    location = item.get("location") or ""
    return {
        "id": f"li-{job_id}",
        "job_id": job_id,
        "title": title,
        "company": (item.get("companyName") or "").strip(),
        "company_linkedin": (item.get("companyLinkedinUrl") or "").split("?")[0],
        "website": item.get("companyWebsite") or "",
        "employees": str(item.get("companyEmployeesCount") or ""),
        "industry": item.get("industries") or "",
        "location": location,
        "posted": (item.get("postedAt") or "")[:10],
        "applicants": str(item.get("applicantsCount") or ""),
        "salary": item.get("salary") or salary_in(description),
        "seniority": item.get("seniorityLevel") or "",
        "url": f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else (item.get("link") or "").split("?")[0],
        "apply_url": item.get("applyUrl") or "",
        "fit": title_score(title),
        "flags": flags_for(location, description),
        "snippet": re.sub(r"\s+", " ", description)[:SNIPPET],
    }


def filter_jobs(items: list[dict[str, Any]], cfg: RadarConfig) -> list[dict[str, Any]]:
    """One row per LinkedIn job: GTM titles, no staffing agencies, roles that fit."""
    by_id: dict[str, dict[str, Any]] = {}
    for item in items:
        job = parse_job(item)
        if job["job_id"]:
            by_id.setdefault(job["job_id"], job)
    return [
        j
        for j in by_id.values()
        if j["fit"] >= cfg.min_fit
        and j["company"]
        and not AGENCY.search(f"{j['company']} {j['industry']}")
        and fits(j, cfg)[0]
    ]


def search_linkedin(apify: Runner, cfg: RadarConfig, since_seconds: int) -> Found:
    urls = search_urls(cfg, since_seconds)
    result = apify.run(
        LINKEDIN_JOBS,
        {"urls": urls, "limitPerSource": cfg.per_search, "scrapeCompany": True},
        cfg.daily_usd,
        partial_ok=True,
    )
    kept = filter_jobs(result.items, cfg)
    spent = round(len(result.items) * PRICE_PER_JOB, 2)
    return Found(kept, {"searches": len(urls), "scanned": len(result.items), "kept": len(kept), "spent_usd": spent})


# ----------------------------------------------------------------------------- company job boards through Google


def ats_queries(cfg: RadarConfig) -> str:
    return "\n".join(f'site:{site} "{k.strip()}"' for site in ATS_SITES for k in cfg.keywords[:3] if k.strip())


def search_ats(apify: Runner, web: boards.Http, cfg: RadarConfig, days: int, today: date) -> Found:
    """Roles posted straight to company job boards: these often never reach LinkedIn, so fewer people apply."""
    result = apify.run(
        GOOGLE_SEARCH,
        {
            "queries": ats_queries(cfg),
            "maxPagesPerQuery": 1,
            "quickDateRange": f"d{max(1, days)}",
            "countryCode": "us",
            "searchLanguage": "en",
            "saveHtmlToKeyValueStore": False,
        },
        GOOGLE_CAP_USD,
        partial_ok=True,
    )
    wanted: dict[tuple[str, str], set[str]] = {}
    for page in result.items:
        for hit in page.get("organicResults") or []:
            for ats, rx in ATS_LINK:
                if m := re.search(rx, hit.get("url") or "", re.IGNORECASE):
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
    meta = {"boards": len(wanted), "read": len(found), "kept": len(kept), "charged_usd": result.charged_usd}
    return Found(kept, meta)


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


def search_posts(apify: Runner, window: str) -> Found:
    result = apify.run(
        POST_SEARCH,
        {
            "searchQueries": POST_QUERIES,
            "maxPosts": POSTS_PER_QUERY,
            "postedLimit": window,
            "sortBy": "date",
            "profileScraperMode": "short",
            "scrapeReactions": False,
            "scrapeComments": False,
        },
        POSTS_CAP_USD,
        partial_ok=True,
    )
    kept: dict[str, dict[str, Any]] = {}
    for post in result.items:
        if (h := hiring_post(post)) and h["id"]:
            kept.setdefault(h["id"], h)
    meta = {"scanned": len(result.items), "kept": len(kept), "window": window, "charged_usd": result.charged_usd}
    return Found(list(kept.values()), meta)
