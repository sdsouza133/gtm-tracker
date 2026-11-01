"""Build one lead magnet: from a prospect's website to the people in their ICP who keep engaging with competitors.

1. Read the prospect's site (free) and have Claude work out the ICP and competitors.
2. Find each competitor's LinkedIn page (Apollo) and, for the full build, two of its decision makers.
3. Read their last month of posts and keep the most engaged ones, then pull each post's likes and comments.
4. Count touchpoints per person (see `touch`): a like is one touch, not intent.
5. Drop the obvious non-buyers by rule, then have Claude screen the rest against the ICP.
6. Look up the best-fitting people's profiles, keep only those in the US or Canada, and (full build) find their work
   emails with Apollo.

The teaser is one competitor and a handful of examples, cheap enough to send cold; the full build is three
competitors with emails, for prospects who replied. Every paid call draws on the build's budget.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

from pydantic import SecretStr

from app.config import Settings
from app.enrich.apollo import Apollo, ApolloError, work_email
from app.magnet import touch
from app.magnet.brain import ICP, Brain, Competitor, Thinker
from app.magnet.linkedin import PRICE, PROFILES, Engager, LinkedIn, LinkedInError, Post, Profile
from app.magnet.site import read_site
from app.radar.apify import Apify
from app.radar.fit import domain_of, web_url

Mode = Literal["teaser", "full"]
Progress = Callable[[str, dict[str, Any]], None]

REGIONS = frozenset({"US", "CA"})
DECISION_MAKER_TITLES = [
    "CEO",
    "Founder",
    "Co-Founder",
    "Chief Marketing Officer",
    "Chief Revenue Officer",
    "VP Marketing",
    "VP Sales",
    "Head of Marketing",
    "Head of Growth",
]
NOT_BUYERS = re.compile(
    r"\b(recruit\w*|talent acquisition|talent partner|sourcer|headhunt\w*|students?|intern|internship|"
    r"open to work|opentowork|job seeker|aspiring|seeking (new )?(opportunit\w+|roles?|positions?)|"
    r"looking for (new |my next )?(opportunit\w+|roles?|positions?))\b",
    re.IGNORECASE,
)
# an ICP whose buyers are recruiters, talent teams or students: then those headlines are the point, not noise
SELLS_TO_RECRUITERS_OR_STUDENTS = re.compile(r"recruit|talent|sourc|student|universit|campus", re.IGNORECASE)
SAID_KEPT = 2  # comments quoted per lead
MIN_NAME = 3  # shorter company names match too many headlines by accident


class BuildError(RuntimeError):
    pass


@dataclass(frozen=True)
class Plan:
    competitors: int
    decision_makers: int  # per competitor, whose own posts are read too
    posts_per_target: int  # posts read per page or person
    posts_per_competitor: int  # of those, the most engaged ones mined for likes and comments
    reactions: int  # per post
    comments: int  # per post
    profiles: int  # the best-fitting people looked up for location and current job
    emails: bool
    budget_usd: float  # Apify spend; Claude and Apollo are on top (a few cents and credits)


PLANS: dict[Mode, Plan] = {
    "teaser": Plan(
        competitors=1,
        decision_makers=0,
        posts_per_target=5,
        posts_per_competitor=3,
        reactions=30,
        comments=15,
        profiles=15,
        emails=False,
        budget_usd=0.40,
    ),
    "full": Plan(
        competitors=3,
        decision_makers=2,
        posts_per_target=6,
        posts_per_competitor=3,
        reactions=50,
        comments=20,
        profiles=100,
        emails=True,
        budget_usd=2.00,
    ),
}


class Finder(Protocol):
    def organization(self, domain: str) -> dict[str, Any] | None: ...

    def search_people(self, domain: str, titles: list[str], limit: int) -> list[dict[str, Any]]: ...

    def match_id(self, person_id: str) -> dict[str, Any] | None: ...

    def match(self, *, name: str, domain: str | None, linkedin: str | None) -> dict[str, Any] | None: ...


@dataclass
class Tools:
    """What a build talks to; tests swap in fakes."""

    read_site: Callable[[str], dict[str, Any]]
    brain: Thinker
    linkedin: LinkedIn
    apollo: Finder


def default_tools(settings: Settings) -> Tools:
    """The real network. Raises (BrainError, ApifyError or ApolloError) naming the setting that's missing."""

    def secret(value: SecretStr | None) -> str:
        return value.get_secret_value() if value else ""

    return Tools(
        read_site=read_site,
        brain=Brain(secret(settings.anthropic_api_key), settings.magnet_icp_model, settings.magnet_screen_model),
        linkedin=LinkedIn(Apify(secret(settings.apify_token))),
        apollo=Apollo(secret(settings.apollo_api_key)),
    )


@dataclass(frozen=True)
class Spec:
    mode: Mode
    company: str
    website: str
    competitors: tuple[str, ...] = ()  # domains the user named; they go first


@dataclass
class Budget:
    limit: float
    spent: float = 0.0

    def left(self, keep: float = 0.0) -> float:
        return max(0.0, self.limit - self.spent - keep)

    def add(self, usd: float) -> None:
        self.spent += usd


@dataclass
class Rival:
    """A competitor whose LinkedIn we read."""

    name: str
    domain: str
    linkedin: str
    why: str
    people: list[dict[str, str]] = field(default_factory=list)  # decision makers: name, title, linkedin
    posts: list[str] = field(default_factory=list)  # the posts mined

    def report(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "domain": self.domain,
            "linkedin": self.linkedin,
            "why": self.why,
            "people": self.people,
            "posts": self.posts,
        }


def build(spec: Spec, tools: Tools, today: date, progress: Progress | None = None) -> dict[str, Any]:
    """The finished report as plain data. Raises BuildError when there's nothing to build from."""
    say = progress or (lambda _step, _info: None)
    plan = PLANS[spec.mode]
    budget = Budget(plan.budget_usd)

    say("reading the website", {"website": spec.website})
    site = tools.read_site(spec.website)
    say("working out the ICP", {"pages": len(site.get("pages") or [])})
    icp = tools.brain.icp(site, list(spec.competitors))

    say("finding competitors on LinkedIn", {"suggested": [c.name for c in icp.competitors]})
    rivals = _rivals(spec, icp, tools.apollo, plan)
    if not rivals:
        raise BuildError("None of the competitors has a LinkedIn page Apollo knows. Name one and try again.")

    keep_for_profiles = plan.profiles * PRICE[PROFILES]
    say("reading their posts", {"competitors": [r.name for r in rivals]})
    posts = _posts(rivals, tools.linkedin, plan, budget, keep_for_profiles)
    if not posts:
        raise BuildError("The competitors haven't posted on LinkedIn in the last month.")

    say("pulling likes and comments", {"posts": len(posts)})
    owner = {p.url: r for r in rivals for p in posts if p.url in r.posts}
    engagers, failed = _engage(posts, tools.linkedin, plan, budget, keep_for_profiles, say)
    touches = [
        touch.Touch(person=e.key, post=e.post, competitor=owner[e.post].domain, kind=e.kind, day=e.day, text=e.text)
        for e in engagers
        if e.post in owner
    ]
    scores = touch.ranked(touch.score(touches, today))
    seen = _first_seen(engagers)

    rule_out = [r.name for r in rivals] + [spec.company]
    sells_to_them = bool(SELLS_TO_RECRUITERS_OR_STUDENTS.search(" ".join([*icp.titles, *icp.functions])))
    candidates = [s for s in scores if not _ruled_out(seen[s.person].headline, rule_out, keep_roles=sells_to_them)]
    say("screening against the ICP", {"people": len(scores), "after_rules": len(candidates)})
    verdicts = tools.brain.screen([seen[s.person].headline for s in candidates], icp, rule_out)
    fits = [(s, verdicts[i].reason) for i, s in enumerate(candidates) if i in verdicts and verdicts[i].fit]

    room = min(plan.profiles, int(budget.left() / PRICE[PROFILES]))
    looked = fits[:room]
    say("checking where they are", {"fit": len(fits), "looking_up": len(looked)})
    profiles, spent = tools.linkedin.profiles([seen[s.person].url for s, _ in looked], budget.left())
    budget.add(spent)

    leads = [
        _lead(s, profiles[s.person], seen[s.person], reason, engagers, owner)
        for s, reason in looked
        if s.person in profiles
        and profiles[s.person].country in REGIONS
        and not _works_at(profiles[s.person].company, rule_out)
    ]

    emails: dict[str, Any] = {"asked": 0, "found": 0, "error": ""}
    if plan.emails and leads:
        say("finding work emails", {"leads": len(leads)})
        emails = _emails(leads, tools.apollo)

    return {
        "mode": spec.mode,
        "company": spec.company,
        "website": spec.website,
        "built": today.isoformat(),
        "icp": icp.model_dump(exclude={"competitors"}),
        "competitors": [r.report() for r in rivals],
        "leads": leads,
        "stats": {
            "posts": len(posts),
            "posts_failed": failed,
            "engagements": len(touches),
            "people": len(scores),
            "after_rules": len(candidates),
            "fit": len(fits),
            "looked_up": len(looked),
            "in_region": len(leads),
            "tiers": {t: sum(1 for lead in leads if lead["tier"] == t) for t in ("hot", "warm", "touch")},
            "emails": emails,
            "apify_usd": round(budget.spent, 3),
        },
    }


def _rivals(spec: Spec, icp: ICP, apollo: Finder, plan: Plan) -> list[Rival]:
    """Competitors with a LinkedIn page, the user's own picks first, up to the plan's number."""
    own = domain_of(spec.website)
    named = [Competitor(name=d, domain=d, why="You named them.") for d in spec.competitors]
    rivals: list[Rival] = []
    tried: set[str] = set()
    for c in [*named, *icp.competitors]:
        if len(rivals) >= plan.competitors:
            break
        domain = domain_of(c.domain)
        if not domain or "." not in domain or domain == own or domain in tried:
            continue
        tried.add(domain)
        try:
            org = apollo.organization(domain) or {}
        except ApolloError:
            continue
        linkedin = _https(org.get("linkedin_url"))
        if "/company/" not in linkedin:
            continue
        rival = Rival(name=str(org.get("name") or c.name), domain=domain, linkedin=linkedin, why=c.why)
        if plan.decision_makers:
            rival.people = _decision_makers(apollo, domain, plan.decision_makers)
        rivals.append(rival)
    return rivals


def _decision_makers(apollo: Finder, domain: str, limit: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    try:
        found = apollo.search_people(domain, DECISION_MAKER_TITLES, limit)
        for p in found:
            person = apollo.match_id(str(p["id"])) or {}
            linkedin = _https(person.get("linkedin_url"))
            if "/in/" in linkedin:
                out.append(
                    {
                        "name": str(person.get("name") or ""),
                        "title": str(person.get("title") or ""),
                        "linkedin": linkedin,
                    }
                )
    except ApolloError:
        pass  # the company page alone still works
    return out


def _posts(rivals: list[Rival], linkedin: LinkedIn, plan: Plan, budget: Budget, keep: float) -> list[Post]:
    """Each competitor's most engaged posts from the last month, across its page and its decision makers."""
    by_target: dict[str, Rival] = {}
    for r in rivals:
        by_target[_key(r.linkedin)] = r
        for p in r.people:
            by_target[_key(p["linkedin"])] = r
    pages = [r.linkedin for r in rivals]
    people = [p["linkedin"] for r in rivals for p in r.people]
    found, spent = linkedin.posts(pages, plan.posts_per_target, budget.left(keep))
    budget.add(spent)
    if people:
        try:
            more, spent = linkedin.posts(people, plan.posts_per_target, budget.left(keep), people=True)
        except LinkedInError as e:
            more, spent = [], e.spent  # the decision makers are extra; the company pages alone still work
        budget.add(spent)
        found += more
    chosen: list[Post] = []
    for r in rivals:
        mine = {p.url: p for p in found if by_target.get(_key(p.target)) is r and (p.likes or p.comments)}
        best = sorted(mine.values(), key=lambda p: (-p.weight, p.url))[: plan.posts_per_competitor]
        r.posts = [p.url for p in best]
        chosen += best
    return chosen


def _engage(
    posts: list[Post], linkedin: LinkedIn, plan: Plan, budget: Budget, keep: float, say: Progress
) -> tuple[list[Engager], int]:
    """Every post's likes and comments, and how many posts failed. One post failing still leaves the others. Each post
    reports progress, so a long build keeps showing signs of life."""
    engagers: list[Engager] = []
    failed = 0
    for n, post in enumerate(posts, start=1):
        say(f"pulling likes and comments ({n} of {len(posts)} posts)", {"post": post.url})
        try:
            found, spent = linkedin.engagers(post, plan.reactions, plan.comments, budget.left(keep))
        except LinkedInError as e:
            budget.add(e.spent)  # what a failed post cost before it failed still counts
            failed += 1
            continue
        budget.add(spent)
        engagers += found
    if failed == len(posts):
        raise BuildError("Apify couldn't read the likes and comments. Try again in a few minutes.")
    return engagers, failed


def _first_seen(engagers: list[Engager]) -> dict[str, Engager]:
    """Each person's details from their first engagement, preferring one with a public profile URL."""
    out: dict[str, Engager] = {}
    for e in engagers:
        have = out.get(e.key)
        if have is None or ("/in/ACoA" in have.url and "/in/ACoA" not in e.url):
            out[e.key] = e
    return out


def _ruled_out(headline: str, names: list[str], *, keep_roles: bool = False) -> bool:
    """A recruiter, student or job seeker, or someone whose headline names the prospect or a competitor (they work
    there, or sell its services). With `keep_roles` (the ICP is recruiters or students), only the second applies."""
    return (not keep_roles and bool(NOT_BUYERS.search(headline or ""))) or _works_at(headline, names)


def _works_at(text: str, names: list[str]) -> bool:
    low = (text or "").lower()
    return any(
        re.search(rf"(?<![a-z0-9]){re.escape(n.lower())}(?![a-z0-9])", low) for n in names if len(n.strip()) >= MIN_NAME
    )


def _lead(
    s: touch.Score, prof: Profile, first: Engager, reason: str, engagers: list[Engager], owner: dict[str, Rival]
) -> dict[str, Any]:
    said = [e.text for e in engagers if e.key == s.person and e.kind == "comment" and e.text][:SAID_KEPT]
    return {
        "name": prof.name or first.name,
        "title": prof.title,
        "company": prof.company,
        "company_linkedin": prof.company_linkedin,
        "headline": prof.headline or first.headline,
        "linkedin": prof.url,
        "country": prof.country,
        "tier": s.tier,
        "points": s.points,
        "touches": s.touches,
        "comments": s.comments,
        "reactions": s.reactions,
        "posts": len(s.posts),
        "competitors": sorted({owner[p].name for p in s.posts if p in owner}),
        "last": s.last.isoformat() if s.last else None,
        "said": said,
        "why_fit": reason,
    }


def _emails(leads: list[dict[str, Any]], apollo: Finder) -> dict[str, Any]:
    """Work emails from Apollo by LinkedIn profile, one credit each. Stops at the first error (out of credits, say)."""
    asked = found = 0
    for lead in leads:
        if "/in/" not in lead["linkedin"]:
            continue
        asked += 1
        try:
            person = apollo.match(name=lead["name"], domain=None, linkedin=lead["linkedin"])
        except ApolloError as e:
            return {"asked": asked, "found": found, "error": str(e)[:200]}
        email = work_email(person)
        if email:
            found += 1
            lead["email"] = email
            lead["email_status"] = str((person or {}).get("email_status") or "")
    return {"asked": asked, "found": found, "error": ""}


def _https(url: Any) -> str:
    u = web_url(str(url or "")).replace("http://", "https://", 1)
    return u.rstrip("/") + "/" if u else ""


def _key(url: str) -> str:
    """A LinkedIn page or profile as a comparable key: its path, without host, query (`?miniProfileUrn=…`), a
    trailing slash or a `/posts` tab."""
    try:
        path = urlsplit((url or "").strip()).path.lower().rstrip("/")
    except ValueError:
        return ""
    return path.removesuffix("/posts").removesuffix("/recent-activity/all")
