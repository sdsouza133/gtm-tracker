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
from app.treg import Caller, TregError

COMPANY_POSTS = "harvestapi.linkedin.company.posts"
PROFILE_POSTS = "harvestapi.linkedin.user.posts"
REACTIONS = "harvestapi.linkedin.post.reactions"
COMMENTS = "harvestapi.linkedin.post.comments"
PROFILES = "harvestapi.linkedin.user.profile.main"  # the profile as LinkedIn first shows it: enough for where and what
PRICE = {COMPANY_POSTS: 0.004, PROFILE_POSTS: 0.004, REACTIONS: 0.004, COMMENTS: 0.004, PROFILES: 0.004}  # $ a call
PROFILE_WORKERS = 3  # treg shares its HarvestAPI account: a few profiles at a time, not a burst
MEMBER_ID = re.compile(r"/in/(ACo[A-Za-z0-9_-]+)")


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

    def _pages(self, tool: str, query: dict[str, str], want: int, max_usd: float) -> tuple[list[dict[str, Any]], float]:
        """Up to `want` items, a page at a time, while the budget covers a whole call."""
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
            token = str(pagination.get("paginationToken") or "")
            last = pagination.get("totalPages")
            if not got or (page >= int(last) if last is not None else not token):
                break
            page += 1
        return items[:want], spent

    def posts(
        self, targets: list[str], per_target: int, max_usd: float, *, people: bool = False
    ) -> tuple[list[Post], float]:
        """The last month's posts by company pages (or, with `people`, by people), newest first per target."""
        tool = PROFILE_POSTS if people else COMPANY_POSTS
        out: list[Post] = []
        spent = 0.0
        for target in targets:
            query = {"profile" if people else "company": target, "postedLimit": "month"}
            try:
                items, cost = self._pages(tool, query, per_target, max_usd - spent)
            except LinkedInError as e:  # the posts already read were paid for
                found = out + [p for p in (parse_post(i, target) for i in e.read) if p]
                raise LinkedInError(str(e), spent=spent + e.spent, posts=found) from e
            spent += cost
            out += [p for p in (parse_post(i, target) for i in items) if p]
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
