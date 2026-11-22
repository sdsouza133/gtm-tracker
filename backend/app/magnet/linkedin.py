"""LinkedIn through HarvestAPI's endpoints on treg (treg.to), which need no LinkedIn login or cookies.

Each call is one page (up to 50 or 100 posts, 100 likes or comments) or one profile, at a set price per call, so the
build's budget is checked before every call and the spend counted is what treg reports charging.
"""

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.magnet.touch import Kind
from app.radar.fit import norm, web_url
from app.treg import Caller, TregError

COMPANY_POSTS = "harvestapi.linkedin.company.posts"
PROFILE_POSTS = "harvestapi.linkedin.user.posts"
REACTIONS = "harvestapi.linkedin.post.reactions"
COMMENTS = "harvestapi.linkedin.post.comments"
PROFILES = "harvestapi.linkedin.user.profile.main"  # the profile as LinkedIn first shows it: enough for where and what
COMPANY_SEARCH = "harvestapi.linkedin.company.search"  # a company's LinkedIn page by name
LEADS_SEARCH = "harvestapi.linkedin.leads.search"  # Sales Navigator's filters: past companies, changed jobs lately
HISTORY = "fetchinio.linkedin.user.profile"  # a profile with its whole work history
PRICE = {  # $ a call: the most a call may charge
    COMPANY_POSTS: 0.004,
    PROFILE_POSTS: 0.004,
    REACTIONS: 0.004,
    COMMENTS: 0.004,
    PROFILES: 0.004,
    COMPANY_SEARCH: 0.004,
    LEADS_SEARCH: 0.10,
    HISTORY: 0.002,
}
PROFILE_WORKERS = 3  # treg shares its HarvestAPI account: a few profiles at a time, not a burst
MEMBER_ID = re.compile(r"/in/(ACo[A-Za-z0-9_-]+)")
PAST_COMPANIES = 50  # the most companies one people search can filter on
COMPANY_SUFFIX = re.compile(r"\b(inc|llc|ltd|limited|co|corp|corporation|company|gmbh|plc|pbc)\b\.?", re.I)
INDUSTRY_NOISE = frozenset(
    {"and", "of", "the", "services", "service", "products", "product", "companies", "company", "brands", "brand"}
)


class LinkedInError(RuntimeError):
    """A run that failed. `spent` is what it may have cost, so the budget still counts it. What was paid for before
    the failure isn't lost with it: `found` is the likes and comments already read for the post, `posts` the posts
    already read, and `read` the raw items of the pages read before it."""

    def __init__(
        self,
        message: str,
        spent: float = 0.0,
        found: list["Engager"] | None = None,
        read: list[dict[str, Any]] | None = None,
        posts: list["Post"] | None = None,
    ) -> None:
        super().__init__(message)
        self.spent = spent
        self.found = found or []
        self.read = read or []
        self.posts = posts or []


@dataclass(frozen=True)
class Post:
    url: str
    target: str  # the company page or person whose post it is
    day: date | None
    likes: int
    comments: int
    text: str

    @property
    def weight(self) -> int:
        return self.likes + 3 * self.comments


@dataclass(frozen=True)
class Engager:
    key: str  # LinkedIn's member ID; the same person has the same key on every post
    name: str
    url: str
    headline: str
    kind: Kind
    post: str
    day: date | None
    text: str = ""


@dataclass(frozen=True)
class Profile:
    key: str
    url: str  # the public profile URL, which Apollo can match
    name: str
    headline: str
    country: str
    title: str
    company: str
    company_linkedin: str


class LinkedIn:
    def __init__(self, treg: Caller) -> None:
        self.treg = treg

    def _pages(
        self, tool: str, query: dict[str, str], want: int, max_usd: float, meta: dict[str, Any] | None = None
    ) -> tuple[list[dict[str, Any]], float]:
        """Up to `want` items, a page at a time, while the budget covers a whole call. `meta`, when given, gets the
        last page's pagination (how many there are in all, say)."""
        items: list[dict[str, Any]] = []
        spent = 0.0
        page, token = 1, ""
        while len(items) < want and spent + PRICE[tool] <= max_usd + 1e-9:
            params = {**query, "page": str(page)} | ({"paginationToken": token} if token else {})
            try:
                answer = self.treg.call(tool, query=params, max_usd=PRICE[tool])
            except TregError as e:
                raise LinkedInError(f"{_name(tool)}: {e}", spent=spent + e.spent, read=items[:want]) from e
            spent += answer.cost_usd
            body = answer.body if isinstance(answer.body, dict) else {}
            got = [i for i in body.get("elements") or [] if isinstance(i, dict)]
            items += got
            pagination = body.get("pagination") or {}
            if meta is not None and isinstance(pagination, dict):
                meta.update(pagination)
            token = str(pagination.get("paginationToken") or "")
            last = pagination.get("totalPages")
            if not got or (page >= int(last) if last is not None else not token):
                break
            page += 1
        return items[:want], spent

    def posts(
        self,
        targets: list[str],
        per_target: int,
        max_usd: float,
        *,
        people: bool = False,
        since: date | None = None,
    ) -> tuple[list[Post], float]:
        """Posts by company pages (or, with `people`, by people) since `since`, newest first per target. LinkedIn is
        asked for the last month, but a person's posts come back from further back too, so the date is checked here."""
        tool = PROFILE_POSTS if people else COMPANY_POSTS
        out: list[Post] = []
        spent = 0.0

        def recent(items: list[dict[str, Any]], target: str) -> list[Post]:
            found = [p for p in (parse_post(i, target) for i in items) if p]
            return [p for p in found if since is None or p.day is None or p.day >= since]

        for target in targets:
            query = {"profile" if people else "company": target, "postedLimit": "month"}
            try:
                items, cost = self._pages(tool, query, per_target, max_usd - spent)
            except LinkedInError as e:  # the posts already read were paid for
                raise LinkedInError(str(e), spent=spent + e.spent, posts=out + recent(e.read, target)) from e
            spent += cost
            out += recent(items, target)
        return out, spent

    def engagers(self, post: Post, reactions: int, comments: int, max_usd: float) -> tuple[list[Engager], float]:
        """Up to `reactions` likes and `comments` comments on one post, people only (company pages dropped)."""
        out: list[Engager] = []
        spent = 0.0
        reads: tuple[tuple[Kind, str, int, int], ...] = (
            ("reaction", REACTIONS, reactions, post.likes),
            ("comment", COMMENTS, comments, post.comments),
        )
        for kind, tool, want, there in reads:
            if not (want and there):
                continue
            try:
                items, cost = self._pages(tool, {"post": post.url}, min(want, there), max_usd - spent)
            except LinkedInError as e:  # what was read before it failed was paid for, and still counts as touches
                found = out + _engagers(e.read, kind, post)
                raise LinkedInError(str(e), spent=spent + e.spent, found=found) from e
            spent += cost
            out += _engagers(items, kind, post)
        return out, spent

    def profiles(self, urls: list[str], max_usd: float) -> tuple[dict[str, Profile], float]:
        """Profiles by member key: where they live and where they work now. As many as the budget covers; a profile
        that can't be read is left out, and only all of them failing is an error."""
        urls = urls[: affordable(PROFILES, max_usd)]
        if not urls:
            return {}, 0.0

        def one(url: str) -> tuple[Profile | None, float, TregError | None]:
            m = MEMBER_ID.search(url)
            query = {"main": "true"} | ({"profileId": m.group(1)} if m else {"url": url})
            try:
                answer = self.treg.call(PROFILES, query=query, max_usd=PRICE[PROFILES])
            except TregError as e:
                return None, e.spent, e
            element = answer.body.get("element") if isinstance(answer.body, dict) else None
            return (parse_profile(element) if isinstance(element, dict) else None), answer.cost_usd, None

        with ThreadPoolExecutor(max_workers=PROFILE_WORKERS) as pool:
            results = list(pool.map(one, urls))
        spent = sum(cost for _, cost, _ in results)
        found = [p for p, _, _ in results if p]
        errors = [e for _, _, e in results if e]
        if errors and len(errors) == len(urls):
            raise LinkedInError(f"{_name(PROFILES)}: {errors[0]}", spent=spent)
        return {p.key: p for p in found}, spent

    # ------------------------------------------------------------------------- champion reports

    def companies(self, names: list[str], industries: list[str], max_usd: float) -> tuple[dict[str, "Org"], float]:
        """Each name's LinkedIn company page, as many names as the budget covers, in order. A name with no clear match
        is left out rather than guessed (see `pick_company`)."""
        names = list(dict.fromkeys(n for n in names if n.strip()))[: affordable(COMPANY_SEARCH, max_usd)]
        if not names:
            return {}, 0.0

        def one(name: str) -> tuple[str, Org | None, float]:
            try:
                answer = self.treg.call(
                    COMPANY_SEARCH, query={"search": name, "page": "1"}, max_usd=PRICE[COMPANY_SEARCH]
                )
            except TregError as e:
                return name, None, e.spent
            body = answer.body if isinstance(answer.body, dict) else {}
            found = [o for o in (parse_org(i) for i in body.get("elements") or [] if isinstance(i, dict)) if o]
            return name, pick_company(name, found, industries), answer.cost_usd

        with ThreadPoolExecutor(max_workers=PROFILE_WORKERS) as pool:
            results = list(pool.map(one, names))
        return {name: org for name, org, _ in results if org}, sum(cost for _, _, cost in results)

    def movers(
        self, companies: list[str], titles: list[str], want: int, max_usd: float
    ) -> tuple[list["Mover"], int, float]:
        """People who used to work at any of these companies (LinkedIn company pages), changed jobs in the last 90
        days, and no longer work at one of them; `titles` narrows it to past jobs with those words. Also how many
        LinkedIn found in all. Raises LinkedInError carrying what was read before a page failed."""
        pages = ",".join(companies[:PAST_COMPANIES])
        query = {"pastCompanies": pages, "excludeCurrentCompanies": pages, "recentlyChangedJobs": "true"}
        if titles:
            query["pastJobTitles"] = ",".join(titles)
        meta: dict[str, Any] = {}
        items, spent = self._pages(LEADS_SEARCH, query, want, max_usd, meta)
        found = [m for m in (parse_mover(i) for i in items) if m]
        return found, _int(meta.get("totalElements")) or len(found), spent

    def history(self, urls: list[str], max_usd: float, today: date) -> tuple[dict[str, "History"], float]:
        """Each profile's work history by the URL asked for, as many as the budget covers. One that can't be read is
        left out; only all of them failing is an error."""
        urls = list(dict.fromkeys(urls))[: affordable(HISTORY, max_usd)]
        if not urls:
            return {}, 0.0

        def one(url: str) -> tuple[str, History | None, float, TregError | None]:
            try:
                answer = self.treg.call(HISTORY, query={"profileUrlOrUrn": url}, max_usd=PRICE[HISTORY])
            except TregError as e:
                return url, None, e.spent, e
            body = answer.body if isinstance(answer.body, dict) else {}
            return url, parse_history(body, today), answer.cost_usd, None

        with ThreadPoolExecutor(max_workers=PROFILE_WORKERS) as pool:
            results = list(pool.map(one, urls))
        spent = sum(cost for _, _, cost, _ in results)
        errors = [e for _, _, _, e in results if e]
        if errors and len(errors) == len(urls):
            raise LinkedInError(f"{_name(HISTORY)}: {errors[0]}", spent=spent)
        return {url: h for url, h, _, _ in results if h}, spent


@dataclass(frozen=True)
class Org:
    """A company's LinkedIn page, as the company search shows it."""

    name: str
    linkedin: str
    industry: str
    location: str
    followers: int


@dataclass(frozen=True)
class Job:
    title: str
    company: str
    company_linkedin: str  # empty when LinkedIn has no page for it
    industry: str
    months: int  # time in the job so far, or in all when it's over
    start: date | None = None
    end: date | None = None  # None while it's current


@dataclass(frozen=True)
class Mover:
    """Someone a people search found: who they are and the jobs they hold now."""

    key: str  # LinkedIn's member id
    url: str
    name: str
    location: str
    jobs: tuple[Job, ...]
    hidden: bool  # LinkedIn shows them as "LinkedIn Member": no name or link


@dataclass(frozen=True)
class History:
    url: str  # the public profile address, when the lookup gives one
    jobs: tuple[Job, ...]  # newest first


def _engagers(items: list[dict[str, Any]], kind: Kind, post: Post) -> list[Engager]:
    return [e for e in (parse_engager(i, kind, post) for i in items) if e]


def _name(tool: str) -> str:
    return tool.removeprefix("harvestapi.linkedin.")


def affordable(tool: str, max_usd: float) -> int:
    """How many calls of this tool the budget pays for, so the calls can't charge more than is left."""
    return max(0, int(max_usd / PRICE[tool] + 1e-9))


def _day(value: Any) -> date | None:
    if isinstance(value, dict):
        value = value.get("date")
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def parse_post(item: dict[str, Any], target: str) -> Post | None:
    """One post read from `target`'s page (a company page or a person's profile)."""
    url = str(item.get("linkedinUrl") or "")
    if not url or item.get("type", "post") != "post":
        return None
    engagement = item.get("engagement") or {}
    return Post(
        url=url,
        target=target,
        day=_day(item.get("postedAt")),
        likes=_int(engagement.get("likes")),
        comments=_int(engagement.get("comments")),
        text=str(item.get("content") or "")[:300],
    )


def parse_engager(item: dict[str, Any], kind: Kind, post: Post) -> Engager | None:
    actor = item.get("actor") or {}
    url = str(actor.get("linkedinUrl") or "")
    key = str(actor.get("id") or "")
    if not key or "/company/" in url or actor.get("type") == "company":
        return None
    day = _day(item.get("createdAt")) if kind == "comment" else post.day  # a like carries no date; the post's is close
    return Engager(
        key=key,
        name=str(actor.get("name") or "").strip(),
        url=url,
        headline=str(actor.get("position") or "").strip(),
        kind=kind,
        post=post.url,
        day=day,
        text=str(item.get("commentary") or "")[:500] if kind == "comment" else "",
    )


def parse_profile(item: dict[str, Any]) -> Profile | None:
    key = str(item.get("id") or "")
    if not key:
        return None
    location = item.get("location") or {}
    country = str(location.get("countryCode") or (location.get("parsed") or {}).get("countryCode") or "").upper()
    current = (item.get("currentPosition") or [{}])[0] or {}
    public = str(item.get("publicIdentifier") or "")
    url = f"https://www.linkedin.com/in/{public}" if public else str(item.get("linkedinUrl") or "")
    name = " ".join(str(item.get(k) or "").strip() for k in ("firstName", "lastName")).strip()
    return Profile(
        key=key,
        url=url,
        name=name,
        headline=str(item.get("headline") or "").strip(),
        country=country,
        title=str(current.get("position") or "").strip(),
        company=str(current.get("companyName") or "").strip(),
        company_linkedin=str(current.get("companyLinkedinUrl") or "").strip(),
    )


def parse_org(item: dict[str, Any]) -> Org | None:
    url = web_url(str(item.get("linkedinUrl") or ""))
    name = str(item.get("name") or "").strip()
    if "/company/" not in url or not name:
        return None
    followers = re.sub(r"[^0-9.KkMm]", "", str(item.get("followers") or ""))
    scale = 1_000_000 if followers[-1:].lower() == "m" else 1_000 if followers[-1:].lower() == "k" else 1
    try:
        count = int(float(followers.rstrip("KkMm") or 0) * scale)
    except ValueError:
        count = 0
    return Org(
        name=name,
        linkedin=url.split("?")[0].rstrip("/"),
        industry=str(item.get("industry") or "").strip(),
        location=str((item.get("location") or {}).get("linkedinText") or "").strip(),
        followers=count,
    )


def company_key(name: str) -> str:
    """A company's name as two spellings of it agree on: no Inc. or LLC, no spaces or punctuation."""
    return norm(COMPANY_SUFFIX.sub(" ", name or ""))


def _name_words(name: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", COMPANY_SUFFIX.sub(" ", (name or "").lower()))


def pick_company(name: str, found: list[Org], industries: list[str]) -> Org | None:
    """The page that is this company: the same name (an Inc. or LLC aside), or the whole name followed by a word or two
    ("HexClad" is "HexClad Cookware", but "Ghost" isn't "Ghostly Labs"). Among those, one in the ICP's industries
    first, then the exact name, then the most followed. None when nothing matches: a wrong page would bring in the
    wrong people."""
    want = _name_words(name)
    if not want:
        return None
    words = {w for i in industries for w in re.findall(r"[a-z]+", i.lower()) if w not in INDUSTRY_NOISE}

    def in_icp(o: Org) -> bool:
        return bool(words & {w for w in re.findall(r"[a-z]+", o.industry.lower()) if w not in INDUSTRY_NOISE})

    def exact(o: Org) -> bool:
        return company_key(o.name) == company_key(name)

    def close(o: Org) -> bool:
        got = _name_words(o.name)
        return exact(o) or (got[: len(want)] == want and len(got) <= len(want) + 2)

    return max((o for o in found if close(o)), key=lambda o: (in_icp(o), exact(o), o.followers), default=None)


def _company_url(company: dict[str, Any]) -> str:
    """A LinkedIn company page from what a people search gives: its address, or its id inside a URN."""
    url = web_url(str(company.get("linkedinUrl") or company.get("url") or ""))
    if url:
        return url.split("?")[0].rstrip("/")
    m = re.search(r":(\d+)$", str(company.get("entityUrn") or ""))
    return f"https://www.linkedin.com/company/{m.group(1)}" if m else ""


def parse_mover(item: dict[str, Any]) -> Mover | None:
    key = str(item.get("id") or item.get("linkedinUrl") or "")
    if not key:
        return None
    url = web_url(str(item.get("linkedinUrl") or "")).split("?")[0]
    name = " ".join(str(item.get(k) or "").strip() for k in ("firstName", "lastName")).strip()
    jobs = []
    for p in item.get("currentPositions") or []:
        if not isinstance(p, dict):
            continue
        company = _dict(p.get("company"))
        tenure = p.get("tenureAtPosition") or {}
        jobs.append(
            Job(
                title=str(p.get("title") or "").strip(),
                company=str(p.get("companyName") or company.get("name") or "").strip(),
                company_linkedin=_company_url(company),
                industry=str(company.get("industry") or "").strip(),
                months=_int(tenure.get("numYears")) * 12 + _int(tenure.get("numMonths")),
            )
        )
    hidden = not url or not name or name.lower() == "linkedin member"
    location = str((item.get("location") or {}).get("linkedinText") or "").strip()
    return Mover(key=key, url=url, name=name, location=location, jobs=tuple(jobs), hidden=hidden)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _month(value: Any) -> date | None:
    if not isinstance(value, dict) or not value.get("year"):
        return None
    try:
        return date(int(value["year"]), min(12, max(1, int(value.get("month") or 1))), 1)
    except (TypeError, ValueError):
        return None


def parse_history(body: dict[str, Any], today: date) -> History:
    """A profile lookup's work history, newest first. The experiences sit at the top or under `raw`, depending on
    how the answer is wrapped."""
    raw = _dict(body.get("raw")) or body
    public = str(raw.get("publicIdentifier") or "")
    url = web_url(str(raw.get("url") or "")) or (f"https://www.linkedin.com/in/{public}" if public else "")
    jobs = []
    for e in raw.get("experiences") or raw.get("experience") or []:
        if not isinstance(e, dict):
            continue
        period = _dict(e.get("timePeriod"))
        start, end = _month(period.get("startDate")), _month(period.get("endDate"))
        company = _dict(e.get("company"))
        months = 0
        if start:
            last = end or today
            months = max(0, (last.year - start.year) * 12 + last.month - start.month)
        jobs.append(
            Job(
                title=str(e.get("jobTitle") or e.get("title") or "").strip(),
                company=str(company.get("name") or e.get("name") or e.get("companyName") or "").strip(),
                company_linkedin=web_url(str(company.get("url") or "")).split("?")[0].rstrip("/"),
                industry="",
                months=months,
                start=start,
                end=end,
            )
        )
    jobs.sort(key=lambda j: (j.end is None, j.end or date.max, j.start or date.min), reverse=True)
    return History(url=url.split("?")[0].rstrip("/"), jobs=tuple(jobs))
