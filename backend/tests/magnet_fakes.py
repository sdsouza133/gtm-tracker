"""Stand-ins for Apify, Claude and Apollo in lead magnet tests. Every company, person and post here is made up."""

from typing import Any

from app.magnet import linkedin as li
from app.magnet.brain import ICP, Competitor, Verdict
from app.radar.apify import RunResult

RIVAL_PAGE = "https://www.linkedin.com/company/rivalco/"
OTHER_PAGE = "https://www.linkedin.com/company/otherco/"


def post(url: str, target: str, likes: int, comments: int, day: str = "2026-10-28") -> dict[str, Any]:
    return {
        "type": "post",
        "linkedinUrl": url,
        "content": "A post about pipelines",
        "postedAt": {"date": f"{day}T12:00:00.000Z"},
        "engagement": {"likes": likes, "comments": comments},
        "author": {"type": "company", "name": "RivalCo", "linkedinUrl": target + "posts"},
        "query": {"targetUrl": target},
    }


def reaction(key: str, name: str, headline: str, post_url: str) -> dict[str, Any]:
    return {
        "reactionType": "LIKE",
        "actor": {
            "id": key,
            "name": name,
            "linkedinUrl": f"https://www.linkedin.com/in/{key}",
            "position": headline,
        },
        "query": {"post": post_url},
    }


def company_reaction(post_url: str) -> dict[str, Any]:
    return {
        "reactionType": "LIKE",
        "actor": {"id": "991", "name": "Some Agency", "linkedinUrl": "https://www.linkedin.com/company/someagency/"},
        "query": {"post": post_url},
    }


def comment(key: str, public: str, headline: str, post_url: str, text: str, day: str = "2026-10-29") -> dict[str, Any]:
    return {
        "commentary": text,
        "createdAt": f"{day}T09:00:00.000Z",
        "actor": {
            "id": key,
            "type": "profile",
            "name": public.replace("-", " ").title(),
            "linkedinUrl": f"https://www.linkedin.com/in/{public}",
            "position": headline,
        },
        "query": {"post": post_url},
    }


def profile(key: str, public: str, country: str, title: str = "VP Sales", company: str = "Buyer Inc") -> dict[str, Any]:
    first, _, last = public.replace("-", " ").title().partition(" ")
    return {
        "id": key,
        "publicIdentifier": public,
        "firstName": first,
        "lastName": last,
        "headline": f"{title} at {company}",
        "location": {"countryCode": country},
        "currentPosition": [
            {"position": title, "companyName": company, "companyLinkedinUrl": "https://www.linkedin.com/company/buyer/"}
        ],
    }


class FakeRunner:
    """Answers each actor run from canned items; engagement runs are answered per post. Records every run."""

    def __init__(
        self,
        posts: list[dict[str, Any]] | None = None,
        people_posts: list[dict[str, Any]] | None = None,
        reactions: dict[str, list[dict[str, Any]]] | None = None,
        comments: dict[str, list[dict[str, Any]]] | None = None,
        profiles: list[dict[str, Any]] | None = None,
        fail: set[str] | None = None,
        status: str = "SUCCEEDED",
    ) -> None:
        self.status = status
        self.posts = posts or []
        self.people_posts = people_posts or []
        self.reactions = reactions or {}
        self.comments = comments or {}
        self.profiles = profiles or []
        self.fail = fail or set()
        self.runs: list[tuple[str, dict[str, Any], float]] = []

    def run(
        self,
        actor: str,
        actor_input: dict[str, Any],
        max_usd: float,
        *,
        partial_ok: bool = False,  # noqa: ARG002
    ) -> RunResult:
        self.runs.append((actor, actor_input, max_usd))
        if actor in self.fail:
            raise RuntimeError(f"{actor} is down")
        items: list[dict[str, Any]]
        if actor == li.COMPANY_POSTS:
            items = [p for p in self.posts if p["query"]["targetUrl"] in actor_input["targetUrls"]]
        elif actor == li.PROFILE_POSTS:
            items = self.people_posts
        elif actor == li.REACTIONS:
            items = self.reactions.get(actor_input["posts"][0], [])[: actor_input["maxItems"]]
        elif actor == li.COMMENTS:
            items = self.comments.get(actor_input["posts"][0], [])[: actor_input["maxItems"]]
        else:
            wanted = {u.rstrip("/").rsplit("/", 1)[-1] for u in actor_input["urls"]}
            items = [p for p in self.profiles if p["id"] in wanted or p["publicIdentifier"] in wanted]
        return RunResult(items=items, status=self.status, charged_usd=0.0)

    def actors(self) -> list[str]:
        return [actor for actor, _, _ in self.runs]


def icp(*competitors: str) -> ICP:
    return ICP(
        company="Prospect",
        sells="Pipeline software for B2B sales teams",
        industries=["B2B SaaS"],
        company_sizes=["50-500"],
        regions=["US", "Canada"],
        titles=["VP Sales", "Head of RevOps"],
        seniority=["VP", "Director"],
        functions=["Sales", "RevOps"],
        exclude=[],
        competitors=[Competitor(name=d.split(".")[0].title(), domain=d, why="Same buyers") for d in competitors],
    )


class FakeBrain:
    """An ICP naming the given competitors; a person fits when their headline mentions sales or revops."""

    def __init__(self, *competitors: str) -> None:
        self.competitors = competitors
        self.screened: list[list[str]] = []
        self.hints: list[list[str]] = []

    def icp(self, site: dict[str, Any], competitors: list[str]) -> ICP:  # noqa: ARG002
        self.hints.append(competitors)
        return icp(*self.competitors)

    def screen(self, headlines: list[str], icp: ICP, exclude: list[str]) -> dict[int, Verdict]:  # noqa: ARG002
        self.screened.append(headlines)
        return {
            i: Verdict(i=i, fit=any(w in h.lower() for w in ("sales", "revops")), reason="sells to the buyer")
            for i, h in enumerate(headlines)
        }


class FakeApollo:
    def __init__(
        self,
        orgs: dict[str, dict[str, Any]] | None = None,
        emails: dict[str, str] | None = None,
        people: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        self.orgs = orgs or {}
        self.emails = emails or {}
        self.people = people or {}
        self.matched: list[str] = []
        self.searched: list[str] = []

    def organization(self, domain: str) -> dict[str, Any] | None:
        return self.orgs.get(domain)

    def search_people(self, domain: str, titles: list[str], limit: int) -> list[dict[str, Any]]:  # noqa: ARG002
        self.searched.append(domain)
        return [{"id": p["id"]} for p in self.people.get(domain, [])][:limit]

    def match_id(self, person_id: str) -> dict[str, Any] | None:
        return next((p for ps in self.people.values() for p in ps if p["id"] == person_id), None)

    def match(self, *, name: str, domain: str | None, linkedin: str | None) -> dict[str, Any] | None:  # noqa: ARG002
        self.matched.append(linkedin or "")
        email = self.emails.get(linkedin or "")
        return {"email": email, "email_status": "verified"} if email else None
