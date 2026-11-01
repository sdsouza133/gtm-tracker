"""LinkedIn through Apify's HarvestAPI actors, which need no LinkedIn login or cookies.

Each actor is paid per item, so every run gets a spend cap from the build's budget, and the spend counted is the
larger of what Apify reports and the item count times the list price.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx2

from app.magnet.touch import Kind
from app.radar.apify import MIN_CHARGE_USD
from app.radar.sources import Runner

COMPANY_POSTS = "harvestapi/linkedin-company-posts"
PROFILE_POSTS = "harvestapi/linkedin-profile-posts"
REACTIONS = "harvestapi/linkedin-post-reactions"
COMMENTS = "harvestapi/linkedin-post-comments"
PROFILES = "harvestapi/linkedin-profile-scraper"
PROFILE_MODE = "Profile details no email ($4 per 1k)"
PRICE = {COMPANY_POSTS: 0.002, PROFILE_POSTS: 0.002, REACTIONS: 0.002, COMMENTS: 0.002, PROFILES: 0.004}  # $ per item
CAP_SLACK = 1.25  # Apify's cap sits a little above the list price, so a run isn't stopped one item short


class LinkedInError(RuntimeError):
    """A run that failed. `spent` is what it may have cost, so the budget still counts it; `found` is what earlier runs
    for the same post had already read, so it isn't lost with the failure."""

    def __init__(self, message: str, spent: float = 0.0, found: list["Engager"] | None = None) -> None:
        super().__init__(message)
        self.spent = spent
        self.found = found or []


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
    def __init__(self, runner: Runner) -> None:
        self.runner = runner

    def _run(self, actor: str, actor_input: dict[str, Any], expected: int, max_usd: float) -> tuple[list[Any], float]:
        # Apify won't take a cap under MIN_CHARGE_USD, so with less budget than that left, nothing starts
        if max_usd < MIN_CHARGE_USD or expected <= 0:
            return [], 0.0
        name = actor.rsplit("/", maxsplit=1)[-1]
        cap = min(max_usd, expected * PRICE[actor] * CAP_SLACK + 0.01)
        try:
            result = self.runner.run(actor, actor_input, cap, partial_ok=True)
        except (RuntimeError, httpx2.HTTPError) as e:  # ApifyError, and timeouts or dropped connections
            # the run may have started and be charging, and its cost is now unknown: count all it was allowed to spend
            raise LinkedInError(f"{name}: {type(e).__name__} {e}", spent=cap) from e
        items = [i for i in result.items if isinstance(i, dict)]
        if result.status != "SUCCEEDED" and not items:  # a run stopped at its cap still keeps what it saved
            raise LinkedInError(f"{name} ended {result.status}.", spent=result.charged_usd)
        return items, max(result.charged_usd, len(items) * PRICE[actor])

    def posts(
        self, targets: list[str], per_target: int, max_usd: float, *, people: bool = False
    ) -> tuple[list[Post], float]:
        """The last month's posts by company pages (or, with `people`, by people), newest first per target."""
        if not targets:
            return [], 0.0
        actor = PROFILE_POSTS if people else COMPANY_POSTS
        items, spent = self._run(
            actor,
            {"targetUrls": targets, "maxPosts": per_target, "postedLimit": "month"},
            len(targets) * per_target,
            max_usd,
        )
        return [p for p in (parse_post(i) for i in items) if p], spent

    def engagers(self, post: Post, reactions: int, comments: int, max_usd: float) -> tuple[list[Engager], float]:
        """Up to `reactions` likes and `comments` comments on one post, people only (company pages dropped)."""
        out: list[Engager] = []
        spent = 0.0
        reactions = min(reactions, affordable(REACTIONS, max_usd))
        if reactions and post.likes:
            items, cost = self._run(
                REACTIONS, {"posts": [post.url], "maxItems": reactions}, min(reactions, post.likes), max_usd
            )
            spent += cost
            out += [e for e in (parse_engager(i, "reaction", post) for i in items) if e]
        comments = min(comments, affordable(COMMENTS, max_usd - spent))
        if comments and post.comments:
            try:
                items, cost = self._run(
                    COMMENTS, {"posts": [post.url], "maxItems": comments}, min(comments, post.comments), max_usd - spent
                )
            except LinkedInError as e:  # the likes already read were paid for, and still count as touches
                raise LinkedInError(str(e), spent=spent + e.spent, found=out) from e
            spent += cost
            out += [e for e in (parse_engager(i, "comment", post) for i in items) if e]
        return out, spent

    def profiles(self, urls: list[str], max_usd: float) -> tuple[dict[str, Profile], float]:
        """Profiles by member key: where they live and where they work now. As many as the budget covers."""
        urls = urls[: affordable(PROFILES, max_usd)]
        if not urls:
            return {}, 0.0
        items, spent = self._run(PROFILES, {"urls": urls, "profileScraperMode": PROFILE_MODE}, len(urls), max_usd)
        found = [p for p in (parse_profile(i) for i in items) if p]
        return {p.key: p for p in found}, spent


def affordable(actor: str, max_usd: float) -> int:
    """How many items of this actor the budget pays for, so a run can't charge more than is left."""
    return max(0, int(max_usd / PRICE[actor]))


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


def parse_post(item: dict[str, Any]) -> Post | None:
    url = str(item.get("linkedinUrl") or "")
    if not url or item.get("type", "post") != "post":
        return None
    engagement = item.get("engagement") or {}
    query = item.get("query") or {}
    author = item.get("author") or {}
    target = str(query.get("targetUrl") or query.get("profileUrl") or author.get("linkedinUrl") or "")
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
