"""Stand-ins for the network in radar tests (treg itself is faked in treg_fakes). Every board, company and job here is
made up."""

from datetime import UTC, datetime, timedelta
from typing import Any


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
    job_id: str, title: str, company: str, location: str = "United States (Remote)", **extra: Any
) -> dict[str, Any]:
    """A job as LinkedIn's search lists it, posted an hour ago."""
    slug = company.lower().replace(" ", "-")
    return {
        "id": job_id,
        "url": f"https://www.linkedin.com/jobs/view/{job_id}",
        "title": title,
        "postedDate": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        "company": {"name": company, "universalName": slug, "linkedinUrl": f"https://www.linkedin.com/company/{slug}"},
        "location": {"linkedinText": location},
        **extra,
    }


def job_details(**by_id: dict[str, Any]) -> Any:
    """Full postings by job ID; any other job gets a plain remote posting."""

    def reply(query: dict[str, Any], _body: Any) -> dict[str, Any]:
        job_id = str(query.get("jobId"))
        element = {
            "id": job_id,
            "descriptionText": "Remote role building GTM automation.",
            "applicants": 12,
            "salary": {"text": None, "min": None, "max": None},
            "applyMethod": {"companyApplyUrl": f"https://jobs.example/{job_id}"},
        }
        return {"element": {**element, **by_id.get(job_id, {})}}

    return reply
