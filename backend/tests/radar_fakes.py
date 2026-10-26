"""Stand-ins for the network and Apify in radar tests. Every board, company and job here is made up."""

from typing import Any

from app.radar.apify import RunResult


class FakeWeb:
    """Answers board API URLs from a dict; anything else is a 404."""

    def __init__(self, json_by_url: dict[str, Any] | None = None, text_by_url: dict[str, str] | None = None) -> None:
        self.json_by_url = json_by_url or {}
        self.text_by_url = text_by_url or {}
        self.asked: list[str] = []

    def json(self, url: str) -> Any:
        self.asked.append(url)
        if url not in self.json_by_url:
            raise LookupError(f"404 {url}")
        return self.json_by_url[url]

    def text(self, url: str) -> str:
        self.asked.append(url)
        if url not in self.text_by_url:
            raise LookupError(f"404 {url}")
        return self.text_by_url[url]


class FakeApify:
    """Returns canned items per actor and records each run's input and cap."""

    def __init__(
        self, items_by_actor: dict[str, list[dict[str, Any]]] | None = None, fail: set[str] | None = None
    ) -> None:
        self.items_by_actor = items_by_actor or {}
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
        return RunResult(items=self.items_by_actor.get(actor, []), status="SUCCEEDED", charged_usd=0.1)


def ashby(slug: str, *jobs: dict[str, Any]) -> dict[str, Any]:
    return {f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true": {"jobs": list(jobs)}}


def ashby_job(
    title: str, job_id: str, location: str = "Remote", posted: str = "2026-10-25", **extra: Any
) -> dict[str, Any]:
    return {
        "title": title,
        "jobUrl": f"https://jobs.ashbyhq.com/acme/{job_id}",
        "location": location,
        "publishedAt": f"{posted}T00:00:00Z",
        "descriptionPlain": "Join acme.example to build our GTM systems.",
        **extra,
    }


def linkedin_item(
    job_id: str, title: str, company: str, location: str = "United States", **extra: Any
) -> dict[str, Any]:
    return {
        "id": job_id,
        "title": title,
        "companyName": company,
        "companyLinkedinUrl": f"https://www.linkedin.com/company/{company.lower().replace(' ', '-')}",
        "companyWebsite": f"https://{company.lower().replace(' ', '')}.example",
        "location": location,
        "postedAt": "2026-10-25",
        "descriptionText": "Remote role building GTM automation.",
        **extra,
    }
