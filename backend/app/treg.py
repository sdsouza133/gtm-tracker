"""A small client for treg (https://treg.to): one token in front of many data providers, billed per call from a
prepaid balance.

The tracker reads LinkedIn through HarvestAPI's endpoints on treg (public data, no LinkedIn login or cookies) and
Google through Serper. A call returns one page: 25 jobs, 50 or 100 posts, 100 likes or comments, one profile.

The token goes in a header, never the URL, so it can't end up in a proxy's logs. Every call carries a ceiling
(`X-Treg-Route-Max-Cost`), so treg refuses a call that would cost more than the caller allows, and the amount treg
charged comes back in `X-Treg-Cost-Micro`.
"""

from dataclasses import dataclass
from typing import Any, Protocol

import httpx2

BASE = "https://treg.to"
TIMEOUT_S = 120.0
COST_HEADER = "X-Treg-Cost-Micro"
MAX_COST_HEADER = "X-Treg-Route-Max-Cost"
RETRY_STATUSES = frozenset({408, 425, 429})  # plus every 5xx


class TregError(RuntimeError):
    """A call that failed. `spent` is what it was charged (treg doesn't bill a call the provider failed; a dropped
    connection is counted at its ceiling, since its cost is unknown). `retryable` says whether trying later can help:
    rate limits, timeouts, 5xx."""

    def __init__(self, message: str, *, spent: float = 0.0, retryable: bool = False) -> None:
        super().__init__(message)
        self.spent = spent
        self.retryable = retryable


@dataclass(frozen=True)
class Answer:
    body: Any
    cost_usd: float


class Caller(Protocol):
    def call(
        self, tool: str, *, query: dict[str, Any] | None = None, body: dict[str, Any] | None = None, max_usd: float
    ) -> Answer: ...


class Treg:
    def __init__(
        self, token: str, *, timeout_s: float = TIMEOUT_S, transport: httpx2.BaseTransport | None = None
    ) -> None:
        if not token:
            raise TregError("TREG_TOKEN is not set.")
        self.client = httpx2.Client(
            base_url=BASE, timeout=timeout_s, headers={"X-Treg-Token": token}, transport=transport
        )

    def call(
        self, tool: str, *, query: dict[str, Any] | None = None, body: dict[str, Any] | None = None, max_usd: float
    ) -> Answer:
        """Call one catalog tool: GET with `query`, or POST with a JSON `body`. Raises TregError on any failure,
        including a provider's own error inside an HTTP 200."""
        headers = {MAX_COST_HEADER: f"{max(max_usd, 0.0):.4f}"}
        try:
            if body is None:
                r = self.client.get(f"/call/{tool}", params=query or {}, headers=headers)
            else:
                r = self.client.post(f"/call/{tool}", params=query or {}, json=body, headers=headers)
        except httpx2.TransportError as e:  # it may have reached the provider, and been billed, before the drop
            raise TregError(f"{tool}: couldn't reach treg ({type(e).__name__})", spent=max_usd, retryable=True) from e
        cost = _cost(r, max_usd)
        if r.status_code >= 400:  # noqa: PLR2004
            retryable = r.status_code in RETRY_STATUSES or r.status_code >= 500  # noqa: PLR2004
            raise TregError(f"{tool}: treg {r.status_code} {_reason(r)}", spent=cost, retryable=retryable)
        try:
            answer = r.json()
        except ValueError as e:
            raise TregError(f"{tool}: treg sent an answer we couldn't read", spent=cost, retryable=True) from e
        if isinstance(answer, dict) and answer.get("error"):  # HarvestAPI reports some failures inside a 200
            raise TregError(f"{tool}: {str(answer['error'])[:300]}", spent=cost)
        return Answer(answer, cost)


def _cost(r: httpx2.Response, max_usd: float) -> float:
    """What treg charged, in dollars. An answer that doesn't say is counted at its ceiling."""
    try:
        return int(r.headers[COST_HEADER]) / 1_000_000
    except (KeyError, ValueError):
        return max_usd if r.status_code < 400 else 0.0  # noqa: PLR2004


def _reason(r: httpx2.Response) -> str:
    """treg's refusals say what to do in their body ("insufficient_balance", "route_max_cost", ...)."""
    try:
        body = r.json()
    except ValueError:
        return r.text[:300]
    if isinstance(body, dict):
        for key in ("detail", "error", "message", "code"):
            if body.get(key):
                return str(body[key])[:300]
    return str(body)[:300]
