"""A company's open roles on its public job board.

Greenhouse, Lever, Ashby, SmartRecruiters and Workable all publish free JSON job boards. The board is found from links
on the company's own careers page first (trusted), then from guessed slugs (kept only when a posting names the
company's domain or the board carries the company's name). No API key needed.
"""

import html
import re
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Protocol

import httpx2

from app.radar.fit import OVERSEAS, norm, title_score

TIMEOUT_S = 15
MAX_BYTES = 6_000_000
USER_AGENT = "Mozilla/5.0 (GTM tracker job finder)"
SMARTRECRUITERS_PAGE = 100
SMARTRECRUITERS_MAX = 1000
KEEP_POSTINGS = 8  # best postings kept on the company
SEEN_LIMIT = 400  # posting URLs remembered per company, newest kept
BOARD_LINKS = [
    ("greenhouse", r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_-]+)"),
    ("lever", r"jobs(?:\.eu)?\.lever\.co/([A-Za-z0-9_.-]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)"),
    ("workable", r"apply\.workable\.com/([A-Za-z0-9_-]+)"),
    ("smartrecruiters", r"(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_-]+)"),
]
NOT_SLUGS = frozenset({"embed", "api", "v1", "jobs", "job", "careers", "static", "assets", "js", "css", "search"})
BOARD_URL = {
    "greenhouse": "https://job-boards.greenhouse.io/{}",
    "lever": "https://jobs.lever.co/{}",
    "ashby": "https://jobs.ashbyhq.com/{}",
    "smartrecruiters": "https://jobs.smartrecruiters.com/{}",
    "workable": "https://apply.workable.com/{}",
}


class Http(Protocol):
    def json(self, url: str) -> Any: ...
    def text(self, url: str) -> str: ...


class Web:
    """The real network, with a timeout and a size cap on every response."""

    def __init__(self) -> None:
        self.client = httpx2.Client(timeout=TIMEOUT_S, follow_redirects=True, headers={"User-Agent": USER_AGENT})

    def _get(self, url: str, accept: str) -> bytes:
        with self.client.stream("GET", url, headers={"Accept": accept}) as r:
            r.raise_for_status()
            body = b""
            for chunk in r.iter_bytes():
                body += chunk
                if len(body) > MAX_BYTES:
                    break
            return body

    def json(self, url: str) -> Any:
        import json  # noqa: PLC0415  (only this path parses)

        return json.loads(self._get(url, "application/json"))

    def text(self, url: str) -> str:
        return self._get(url, "text/html").decode("utf-8", "replace")


Posting = dict[str, Any]
Reader = Callable[[Http, str], tuple[str, list[Posting]] | None]


def read_greenhouse(web: Http, slug: str) -> tuple[str, list[Posting]] | None:
    try:
        name = web.json(f"https://boards-api.greenhouse.io/v1/boards/{slug}").get("name", "")
    except Exception:  # the board's name is a nicety; the postings are what matter
        name = ""
    data = web.json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    return name, [
        {
            "title": j.get("title", ""),
            "url": j.get("absolute_url", ""),
            "location": (j.get("location") or {}).get("name", ""),
            "posted": (j.get("first_published") or j.get("updated_at") or "")[:10],
            "text": html.unescape(j.get("content") or "")[:20000],
        }
        for j in data.get("jobs", [])
    ]


def read_lever(web: Http, slug: str) -> tuple[str, list[Posting]] | None:
    data = web.json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    if not isinstance(data, list):
        return None
    return "", [
        {
            "title": j.get("text", ""),
            "url": j.get("hostedUrl", ""),
            "location": (j.get("categories") or {}).get("location", ""),
            "posted": datetime.fromtimestamp(j["createdAt"] / 1000, UTC).date().isoformat()
            if j.get("createdAt")
            else "",
            "text": f"{j.get('descriptionPlain') or ''} {j.get('additionalPlain') or ''}",
        }
        for j in data
    ]


def read_ashby(web: Http, slug: str) -> tuple[str, list[Posting]] | None:
    data = web.json(
        f"https://api.ashbyhq.com/posting-api/job-board/{urllib.parse.quote(slug)}?includeCompensation=true"
    )
    return "", [
        {
            "title": j.get("title", ""),
            "url": j.get("jobUrl") or j.get("applyUrl", ""),
            "location": j.get("location", ""),
            "posted": (j.get("publishedAt") or "")[:10],
            "salary": (j.get("compensation") or {}).get("compensationTierSummary") or "",
            "text": j.get("descriptionPlain") or "",
        }
        for j in data.get("jobs", [])
        if j.get("isListed", True)
    ]


def read_smartrecruiters(web: Http, slug: str) -> tuple[str, list[Posting]] | None:
    postings: list[Posting] = []
    offset, name = 0, ""
    while offset < SMARTRECRUITERS_MAX:
        data = web.json(
            f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit={SMARTRECRUITERS_PAGE}&offset={offset}"
        )
        for j in data.get("content", []):
            name = name or (j.get("company") or {}).get("name", "")
            loc = j.get("location") or {}
            postings.append(
                {
                    "title": j.get("name", ""),
                    "url": f"https://jobs.smartrecruiters.com/{slug}/{j.get('id')}",
                    "location": ", ".join(x for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x),
                    "posted": (j.get("releasedDate") or "")[:10],
                    "text": "",
                }
            )
        offset += SMARTRECRUITERS_PAGE
        if offset >= data.get("totalFound", 0):
            break
    return (name, postings) if postings else None


def read_workable(web: Http, slug: str) -> tuple[str, list[Posting]] | None:
    data = web.json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}")
    return data.get("name", ""), [
        {
            "title": j.get("title", ""),
            "url": j.get("url") or j.get("shortlink", ""),
            "location": ", ".join(x for x in (j.get("city"), j.get("state"), j.get("country")) if x),
            "posted": (j.get("published_on") or j.get("created_at") or "")[:10],
            "text": "",
        }
        for j in data.get("jobs", [])
    ]


READERS: dict[str, Reader] = {
    "greenhouse": read_greenhouse,
    "lever": read_lever,
    "ashby": read_ashby,
    "smartrecruiters": read_smartrecruiters,
    "workable": read_workable,
}


def read(web: Http, ats: str, slug: str) -> tuple[str, list[Posting]] | None:
    """One board, or None when it doesn't exist or can't be read."""
    try:
        return READERS[ats](web, slug)
    except Exception:  # a missing board, a timeout, bad JSON: all mean "not this board"
        return None


def slug_guesses(name: str, domain: str) -> list[str]:
    base = re.sub(r"\b(inc|llc|ltd|co|corp|technologies|technology|labs|hq)\b\.?", "", (name or "").lower()).strip()
    root = (domain or "").lower().removeprefix("www.").split("/")[0]
    host = root.split(".")[0] if root else ""
    candidates = [
        norm(base),
        re.sub(r"[^a-z0-9]+", "-", base).strip("-"),
        host,
        norm(name),
        f"{norm(base)}hq",
        f"{norm(base)}ai",
        f"{host}-inc",
    ]
    for prefix in ("get", "try", "join", "use", "go"):
        if host.startswith(prefix) and len(host) > len(prefix) + 2:
            candidates.append(host[len(prefix) :])
    seen: list[str] = []
    for c in candidates:
        if c and len(c) > 1 and c not in seen:
            seen.append(c)
    return seen


def _page(web: Http, url: str) -> str:
    try:
        return web.text(url)
    except Exception:  # most of these pages don't exist; that's expected
        return ""


def boards_on_careers_page(web: Http, domain: str) -> list[tuple[str, str]]:
    """Job-board slugs linked from the company's own site. These are trusted."""
    if not domain:
        return []
    root = re.sub(r"^https?://", "", domain.lower()).removeprefix("www.").split("/")[0]
    pages = [
        f"https://{root}/careers",
        f"https://www.{root}/careers",
        f"https://{root}/jobs",
        f"https://{root}/company/careers",
        f"https://{root}/about/careers",
        f"https://{root}",
    ]
    found: list[tuple[str, str]] = []
    for url in pages:
        page = _page(web, url)
        for ats, rx in BOARD_LINKS:
            for raw in re.findall(rx, page):
                slug = urllib.parse.unquote(raw).strip(".")
                if slug.lower() not in NOT_SLUGS and (ats, slug) not in found:
                    found.append((ats, slug))
        if found:
            break
    return found


def belongs(name: str, domain: str, board_name: str, postings: list[Posting]) -> str:
    """How sure a guessed board is this company's: "domain" (a posting names their domain), "name", or ""."""
    root = (domain or "").lower().removeprefix("www.").split("/")[0]
    if root and any(
        root in (j.get("text") or "").lower() or root in (j.get("url") or "").lower() for j in postings[:60]
    ):
        return "domain"
    if board_name and norm(board_name) == norm(name):
        return "name"
    return ""


def rank_postings(postings: list[Posting], known_title: str = "") -> list[Posting]:
    """US and Canada first, then closest fit; within that the role we already know about, GTM-named roles, newest."""
    known = norm(known_title)
    postings.sort(key=lambda p: p.get("posted") or "", reverse=True)
    postings.sort(
        key=lambda p: (
            bool(OVERSEAS.search(p.get("location") or "")),
            -p["fit"],
            not (known and (norm(p["title"]) in known or known in norm(p["title"]))),
            not re.search(r"\bgtm\b|go[- ]to[- ]market", p["title"], re.IGNORECASE),
        )
    )
    return postings


@dataclass
class BoardResult:
    board: dict[str, Any] | None
    postings: list[Posting]  # every GTM posting, best first
    note: str

    def as_jobs(self, seen: list[str], first_seen: dict[str, str], today: date) -> dict[str, Any]:
        """The company's `jobs` record: this check's postings, plus every URL seen so far (newest first, capped)."""
        urls = [p["url"] for p in self.postings]
        known = set(seen)
        for p in self.postings:
            p["first_seen"] = first_seen.get(p["url"]) or ("" if p["url"] in known else today.isoformat())
        return {
            "board": self.board,
            "postings": self.postings[:KEEP_POSTINGS],
            "seen": list(dict.fromkeys([*urls, *seen]))[:SEEN_LIMIT],
            "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "note": self.note,
        }


def find_jobs(
    web: Http,
    name: str,
    domain: str = "",
    known_url: str = "",
    known_title: str = "",
    board: dict[str, Any] | None = None,
) -> BoardResult:
    """Find the board (or re-read the one found last time) and list its GTM postings."""
    candidates: list[tuple[str, str, str]] = []
    if known_url:
        for ats, rx in BOARD_LINKS:
            if m := re.search(rx, known_url):
                candidates.append((ats, m.group(1), "known posting"))
    if board:
        candidates.insert(0, (board["ats"], board["slug"], board.get("found_via") or "known board"))
    else:
        candidates += [(ats, slug, "careers page") for ats, slug in boards_on_careers_page(web, domain)]
    for slug in slug_guesses(name, domain):
        candidates += [(ats, slug, "guess") for ats in ("ashby", "greenhouse", "lever", "smartrecruiters")]

    tried: set[tuple[str, str]] = set()
    for ats, slug, how in candidates:
        if (ats, slug.lower()) in tried:
            continue
        tried.add((ats, slug.lower()))
        got = read(web, ats, slug)
        if got is None or (not got[1] and how == "guess"):
            continue  # a known board with no openings is still their board; an empty guess proves nothing
        board_name, jobs = got
        trust = how if how != "guess" else belongs(name, domain, board_name, jobs)
        if not trust:
            continue  # a board with this slug exists, but nothing ties it to this company
        found = {
            "ats": ats,
            "slug": slug,
            "url": BOARD_URL[ats].format(slug),
            "found_via": trust,
            "open_roles": len(jobs),
        }
        postings = [
            {
                "title": j["title"],
                "url": j["url"],
                "location": j.get("location", ""),
                "posted": j.get("posted", ""),
                "salary": j.get("salary", ""),
                "fit": score,
            }
            for j in jobs
            if (score := title_score(j["title"]))
        ]
        rank_postings(postings, known_title)
        note = "" if postings else f"{len(jobs)} open roles on {ats}, none GTM-related right now."
        return BoardResult(found, postings, note)
    return BoardResult(None, [], f"No public job board found (tried {len(tried)}). Check the careers page by hand.")
