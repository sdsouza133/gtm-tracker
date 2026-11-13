"""LinkedIn post search through treg (treg.to), on HarvestAPI's post search: public posts, no login or cookies.

treg answers each call at once, a page of up to 50 posts at a fixed price per call, so `start` runs the whole search
and returns it finished, with its posts. Every call is sent with its list price as its ceiling, and no call starts
that the amount reserved for the search can't cover, so a search never costs more than its reservation.
"""

import math
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx2

from app.events.linkedin import normalize_profile_url
from app.events.providers.pricing import POST_SEARCH_PAGE, POST_SEARCH_PAGE_USD
from app.events.providers.types import ProviderError, SearchedPost, SearchRun, SearchStatus
from app.treg import Caller, Treg, TregError

TOOL = "harvestapi.linkedin.post.search"
SERVICE = "treg"
# LinkedIn itself can only filter posts to the last day, week or month; older windows are filtered after reading.
LINKEDIN_WINDOWS = frozenset({"24h", "week", "month"})
LOST = "the search's posts were lost before they were stored (the worker stopped); it runs again"


class TregPostSearch:
    def __init__(
        self,
        token: str,
        *,
        posted_limit: str = "3months",
        transport: httpx2.BaseTransport | None = None,
        caller: Caller | None = None,
    ) -> None:
        self._treg: Caller = caller or Treg(token, transport=transport)
        self._window = (
            {"postedLimit": posted_limit} if posted_limit in LINKEDIN_WINDOWS else {"scrapePostedLimit": posted_limit}
        )

    def start(self, queries: list[str], *, max_posts_per_query: int, max_charge_usd: Decimal) -> SearchRun:
        pages = max(1, math.ceil(max_posts_per_query / POST_SEARCH_PAGE))
        spent = Decimal(0)
        found: list[SearchedPost] = []
        for query in queries:
            token = ""
            got = 0
            for page in range(1, pages + 1):
                if spent + POST_SEARCH_PAGE_USD > max_charge_usd:
                    break
                params = {"search": query, "sortBy": "relevance", "page": str(page), **self._window}
                if token:
                    params["paginationToken"] = token
                try:
                    answer = self._treg.call(TOOL, query=params, max_usd=float(POST_SEARCH_PAGE_USD))
                except TregError as exc:
                    cost = spent + Decimal(str(exc.spent))
                    raise ProviderError(f"{SERVICE}: {exc}", retryable=exc.retryable, cost_usd=cost) from exc
                spent += Decimal(str(answer.cost_usd))
                body = answer.body if isinstance(answer.body, dict) else {}
                items = [i for i in body.get("elements") or [] if isinstance(i, dict)]
                found += [p for p in (parse_post(i, query) for i in items[: max_posts_per_query - got]) if p]
                got += len(items)
                token = str((body.get("pagination") or {}).get("paginationToken") or "")
                if len(items) < POST_SEARCH_PAGE or got >= max_posts_per_query:
                    break
        return SearchRun(
            id=f"treg-{uuid.uuid4().hex}", status=SearchStatus.SUCCEEDED, cost_usd=spent, posts=tuple(found)
        )

    def get(self, run_id: str) -> SearchRun:
        """treg keeps nothing to come back to: a search the worker didn't store is lost, its cost unknown (so its
        whole reservation is settled), and the search runs again."""
        return SearchRun(id=run_id, status=SearchStatus.FAILED, cost_usd=None, message=LOST)

    def posts(self, run: SearchRun) -> list[SearchedPost]:
        return list(run.posts)


def parse_post(item: dict[str, Any], query: str) -> SearchedPost | None:
    """One search result to a post, or None when it has no id or no text (nothing to judge)."""
    post_id = str(item.get("id") or "")
    text = item.get("content") or (item.get("repost") or {}).get("content") or ""
    if not post_id or not text.strip():
        return None
    author = item.get("author") or {}
    is_company = author.get("type") == "company"
    posted = (item.get("postedAt") or {}).get("date")
    return SearchedPost(
        id=post_id,
        url=item.get("linkedinUrl") or "",
        text=text,
        author_name=author.get("name"),
        author_url=author.get("linkedinUrl") if is_company else normalize_profile_url(author.get("linkedinUrl")),
        author_headline=None if is_company else author.get("info"),
        author_kind="company" if is_company else "person",
        posted_at=_posted_at(posted),
        query=query,
    )


def _posted_at(value: object) -> datetime | None:
    """When the post went up, or None when the date is missing or unreadable: one odd item mustn't fail a search that
    was paid for."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)  # HarvestAPI's timestamps are UTC
