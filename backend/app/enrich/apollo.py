"""A small Apollo client: match people to their work email and LinkedIn profile, and look up what a company does.

The key goes in the X-Api-Key header, never in the URL. Only work emails are asked for; Apollo is told not to reveal
personal ones.
"""

from typing import Any, Protocol

import httpx2

API = "https://api.apollo.io/api/v1"
TIMEOUT_S = 30
BULK = 10  # Apollo matches at most this many people a request
LOCKED = "email_not_unlocked"  # Apollo's placeholder when the plan can't show an email
WEAK = {"low", "none"}  # match_confidence values too unsure to put an email on someone
VERIFIED = "verified"  # the only email_status whose address is kept


class ApolloError(RuntimeError):
    pass


class Finder(Protocol):
    def match(self, *, name: str, domain: str | None, linkedin: str | None) -> dict[str, Any] | None: ...

    def organization(self, domain: str) -> dict[str, Any] | None: ...


class Apollo:
    def __init__(self, key: str, transport: httpx2.BaseTransport | None = None) -> None:
        if not key:
            raise ApolloError("APOLLO_API_KEY is not set.")
        self.client = httpx2.Client(
            base_url=API,
            timeout=TIMEOUT_S,
            headers={"X-Api-Key": key, "Cache-Control": "no-cache"},
            transport=transport,
        )

    def _call(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        try:
            r = self.client.request(method, path, **kw)
        except httpx2.RequestError as e:  # timeouts and dropped connections
            raise ApolloError(f"Apollo unreachable: {type(e).__name__}") from e
        if r.status_code >= 400:  # noqa: PLR2004
            raise ApolloError(f"Apollo {r.status_code}: {r.text[:200]}")
        try:
            body = r.json()
        except ValueError as e:
            raise ApolloError("Apollo sent back something that isn't JSON.") from e
        return body if isinstance(body, dict) else {}

    def match(self, *, name: str, domain: str | None, linkedin: str | None) -> dict[str, Any] | None:
        """The person Apollo matches, or None. A LinkedIn profile matches best; name and domain are the fallback. A name
        alone isn't asked about, and a match Apollo itself is unsure of is dropped, so a stranger's email never lands on
        someone."""
        if not domain and not linkedin:
            return None
        body: dict[str, Any] = {"name": name, "reveal_personal_emails": False, "reveal_phone_number": False}
        if domain:
            body["domain"] = domain
        if linkedin:
            body["linkedin_url"] = linkedin
        person = self._call("POST", "/people/match", json=body).get("person")
        if not isinstance(person, dict) or str(person.get("match_confidence") or "").lower() in WEAK:
            return None
        return person

    def bulk_match(self, details: list[dict[str, Any]]) -> list[dict[str, Any] | None]:
        """The person Apollo matches for each one asked about, in the same order (None where it found no one). Up to
        ten a request. Personal emails and phone numbers are never asked for."""
        if len(details) > BULK:
            raise ValueError(f"Apollo matches at most {BULK} people a request.")
        if not details:
            return []
        body = {"details": details, "reveal_personal_emails": False, "reveal_phone_number": False}
        matches = self._call("POST", "/people/bulk_match", json=body).get("matches")
        found = [m if isinstance(m, dict) else None for m in matches] if isinstance(matches, list) else []
        return (found + [None] * len(details))[: len(details)]

    def organization(self, domain: str) -> dict[str, Any] | None:
        org = self._call("GET", "/organizations/enrich", params={"domain": domain}).get("organization")
        return org if isinstance(org, dict) else None

    def search_people(self, domain: str, titles: list[str], limit: int) -> list[dict[str, Any]]:
        """People at a company with one of these titles, most senior first by Apollo's ranking. Free: Apollo hides
        their last names and LinkedIn until `match_id`."""
        body = {
            "q_organization_domains_list": [domain],
            "person_titles": titles,
            "include_similar_titles": True,
            "per_page": max(1, min(limit, 25)),
            "page": 1,
        }
        people = self._call("POST", "/mixed_people/api_search", json=body).get("people")
        return [p for p in people if isinstance(p, dict) and p.get("id")][:limit] if isinstance(people, list) else []

    def match_id(self, person_id: str) -> dict[str, Any] | None:
        """One person from a search, in full (one credit)."""
        body = {"id": person_id, "reveal_personal_emails": False, "reveal_phone_number": False}
        person = self._call("POST", "/people/match", json=body).get("person")
        return person if isinstance(person, dict) else None


def work_email(person: dict[str, Any] | None) -> str | None:
    """The match's email, unless it's missing or Apollo's locked placeholder."""
    email = str((person or {}).get("email") or "").strip().lower()
    return email if "@" in email and not email.startswith(LOCKED) else None


def verified_email(person: dict[str, Any] | None) -> str | None:
    """The match's work email, only when Apollo has verified it: a guessed or unverified address is never kept."""
    status = str((person or {}).get("email_status") or "").strip().lower()
    return work_email(person) if status == VERIFIED else None
