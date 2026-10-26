"""A small Apify client: start an actor run with a spend cap, wait for it, read its dataset.

The token goes in the Authorization header, never in the URL, so it can't end up in a proxy's logs.
"""

import time
from dataclasses import dataclass
from typing import Any

import httpx2

API = "https://api.apify.com/v2"
WAIT_S = 60  # how long each status call waits server-side
PAGE = 500
MIN_CHARGE_USD = 0.05


class ApifyError(RuntimeError):
    pass


@dataclass(frozen=True)
class RunResult:
    items: list[dict[str, Any]]
    status: str
    charged_usd: float


class Apify:
    def __init__(self, token: str, timeout_s: int = 900) -> None:
        if not token:
            raise ApifyError("APIFY_TOKEN is not set.")
        self.timeout_s = timeout_s
        self.client = httpx2.Client(base_url=API, timeout=WAIT_S + 30, headers={"Authorization": f"Bearer {token}"})

    def _call(self, method: str, path: str, body: Any = None, **params: Any) -> Any:
        r = self.client.request(method, path, json=body, params=params)
        if r.status_code >= 400:  # noqa: PLR2004
            raise ApifyError(f"Apify {r.status_code}: {r.text[:300]}")
        return r.json()

    def run(self, actor: str, actor_input: dict[str, Any], max_usd: float, *, partial_ok: bool = False) -> RunResult:
        """Run an actor to the end. Apify stops it at `max_usd`; with `partial_ok`, a run that stopped early (at the
        cap, say) still returns what it saved."""
        run = self._call(
            "POST",
            f"/acts/{actor.replace('/', '~')}/runs",
            actor_input,
            maxTotalChargeUsd=f"{max(MIN_CHARGE_USD, max_usd):.2f}",
        )["data"]
        deadline = time.monotonic() + self.timeout_s
        while run["status"] in ("READY", "RUNNING"):
            if time.monotonic() > deadline:
                raise ApifyError(f"{actor} took too long.")
            run = self._call("GET", f"/actor-runs/{run['id']}", waitForFinish=WAIT_S)["data"]
        if run["status"] != "SUCCEEDED" and not partial_ok:
            raise ApifyError(f"{actor} ended {run['status']}.")
        items: list[dict[str, Any]] = []
        while True:
            page = self._call(
                "GET", f"/datasets/{run['defaultDatasetId']}/items", clean="true", offset=len(items), limit=PAGE
            )
            items += page
            if len(page) < PAGE:
                break
        return RunResult(items=items, status=run["status"], charged_usd=float(run.get("usageTotalUsd") or 0))
