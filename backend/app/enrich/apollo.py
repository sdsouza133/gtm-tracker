"""A small Apollo client: match a person to their work email, and look up what a company does.

The key goes in the X-Api-Key header, never in the URL. Only work emails are asked for; Apollo is told not to reveal
personal ones.
"""

from typing import Any, Protocol

import httpx2

API = "https://api.apollo.io/api/v1"
TIMEOUT_S = 30
LOCKED = "email_not_unlocked"  # Apollo's placeholder when the plan can't show an email
WEAK = {"low", "none"}  # match_confidence values too unsure to put an email on someone


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

    def organization(self, domain: str) -> dict[str, Any] | None:
        org = self._call("GET", "/organizations/enrich", params={"domain": domain}).get("organization")
        return org if isinstance(org, dict) else None


def work_email(person: dict[str, Any] | None) -> str | None:
    """The match's email, unless it's missing or Apollo's locked placeholder."""
    email = str((person or {}).get("email") or "").strip().lower()
    return email if "@" in email and not email.startswith(LOCKED) else None
