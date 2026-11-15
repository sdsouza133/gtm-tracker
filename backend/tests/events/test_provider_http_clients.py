"""Contract tests for the treg, Apollo and Reoon clients, against synthetic responses shaped like the real
ones (field names and structure copied from live responses; every value is made up)."""

import json
from decimal import Decimal
from typing import Any

import httpx2
import pytest

from app.events.providers.apollo import ApolloEnrichment
from app.events.providers.reoon import ReoonVerifier
from app.events.providers.treg import TregPostSearch, parse_post
from app.events.providers.types import ProviderError, SearchStatus


class Recorder:
    def __init__(self, routes: dict[str, Any]) -> None:
        self.requests: list[httpx2.Request] = []
        self._routes = routes

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        answer = self._routes[request.url.path]
        if callable(answer):
            answer = answer(request)
        return answer if isinstance(answer, httpx2.Response) else httpx2.Response(200, json=answer)


# -------------------------------------------------------------------------------------------------------- treg
SEARCH = "/call/harvestapi.linkedin.post.search"
QUERY = '"RevOps Summit 2026" AND attending'
POST_ITEM = {
    "type": "post",
    "id": "7390000000000000001",
    "linkedinUrl": "https://www.linkedin.com/posts/avery-okafor_revops-activity-7390000000000000001-abcd",
    "content": "Heading to RevOps Summit next week!",
    "author": {
        "type": "profile",
        "name": "Avery Okafor",
        "linkedinUrl": "https://www.linkedin.com/in/Avery-Okafor-1234?miniProfileUrn=urn%3Ali%3Afs",
        "info": "Head of Growth at Northwind Labs",
        "publicIdentifier": "avery-okafor-1234",
    },
    "postedAt": {"timestamp": 1792611808091, "date": "2026-10-21T19:43:28.091Z", "postedAgoShort": "1d"},
}


def page(items: list[dict[str, Any]], token: str = "") -> httpx2.Response:
    body = {"elements": items, "pagination": {"pageSize": 50, "paginationToken": token or None}, "error": None}
    return httpx2.Response(200, json=body, headers={"X-Treg-Cost-Micro": "2000"})


def posts(prefix: str, n: int) -> list[dict[str, Any]]:
    return [dict(POST_ITEM, id=f"{prefix}-{i}") for i in range(n)]


def test_treg_search_answers_at_once_with_every_querys_posts() -> None:
    rec = Recorder({SEARCH: lambda req: page(posts(req.url.params["search"], 3))})
    run = TregPostSearch("tok", transport=httpx2.MockTransport(rec)).start(
        [QUERY, '"RevOps Summit"'], max_posts_per_query=50, max_charge_usd=Decimal("0.40")
    )
    assert (run.status, run.cost_usd, len(run.posts)) == (SearchStatus.SUCCEEDED, Decimal("0.004"), 6)
    assert {p.query for p in run.posts} == {QUERY, '"RevOps Summit"'}
    request = rec.requests[0]
    assert request.headers["X-Treg-Token"] == "tok"
    assert "tok" not in str(request.url)  # the key never goes in a URL a proxy might log
    assert request.headers["X-Treg-Route-Max-Cost"] == "0.0040"  # each call capped at its list price
    assert (request.url.params["scrapePostedLimit"], request.url.params["sortBy"]) == ("3months", "relevance")
    assert "postedLimit" not in request.url.params  # LinkedIn's own filter only goes back a month


def test_treg_search_pages_up_to_the_posts_asked_for_and_never_past_its_reservation() -> None:
    answers = iter([page(posts("a", 50), token="next"), page(posts("b", 50), token="again"), page(posts("c", 50))])
    rec = Recorder({SEARCH: lambda _req: next(answers)})
    search = TregPostSearch("tok", posted_limit="week", transport=httpx2.MockTransport(rec))
    run = search.start([QUERY], max_posts_per_query=120, max_charge_usd=Decimal("0.0065"))
    assert len(rec.requests) == 2  # $0.004 spent, and a third page lists at $0.004: over the $0.0065 reserved
    assert rec.requests[1].url.params["paginationToken"] == "next"
    assert rec.requests[0].url.params["postedLimit"] == "week"
    assert (len(run.posts), run.cost_usd) == (100, Decimal("0.004"))


def test_a_short_page_isnt_the_last_when_the_search_says_there_are_more() -> None:
    def trimmed(req: httpx2.Request) -> httpx2.Response:  # older posts trimmed from each page after reading LinkedIn
        n = int(req.url.params["page"])
        body = {"elements": posts(f"p{n}", 20), "pagination": {"totalPages": 3, "pageNumber": n}}
        return httpx2.Response(200, json=body, headers={"X-Treg-Cost-Micro": "2000"})

    rec = Recorder({SEARCH: trimmed})
    run = TregPostSearch("tok", transport=httpx2.MockTransport(rec)).start(
        [QUERY], max_posts_per_query=200, max_charge_usd=Decimal("0.40")
    )
    assert [r.url.params["page"] for r in rec.requests] == ["1", "2", "3"]  # every page, and none past the last
    assert len(run.posts) == 60


@pytest.mark.parametrize("body", [[], {"elements": {}}, {"pagination": {}}])
def test_an_answer_that_isnt_a_page_of_posts_fails_instead_of_finding_nothing(body: object) -> None:
    answers = iter([page(posts("a", 3)), httpx2.Response(200, json=body, headers={"X-Treg-Cost-Micro": "2000"})])
    rec = Recorder({SEARCH: lambda _req: next(answers)})
    with pytest.raises(ProviderError, match="page of posts") as odd:
        TregPostSearch("tok", transport=httpx2.MockTransport(rec)).start(
            ["first", "second"], max_posts_per_query=50, max_charge_usd=Decimal("0.40")
        )
    assert (odd.value.retryable, odd.value.cost_usd) == (True, Decimal("0.004"))  # both answers were paid for


def test_treg_errors_say_whether_to_retry_and_what_was_spent() -> None:
    answers = iter([page(posts("a", 3)), httpx2.Response(429, json={"detail": "provider_rate_limited"})])
    rec = Recorder({SEARCH: lambda _req: next(answers)})
    with pytest.raises(ProviderError) as busy:
        TregPostSearch("tok", transport=httpx2.MockTransport(rec)).start(
            ["first", "second"], max_posts_per_query=50, max_charge_usd=Decimal("0.40")
        )
    assert (busy.value.retryable, busy.value.cost_usd) == (True, Decimal("0.002"))  # the first page was paid for

    rec = Recorder({SEARCH: httpx2.Response(401, json={"detail": "invalid token"})})
    with pytest.raises(ProviderError) as refused:
        TregPostSearch("bad", transport=httpx2.MockTransport(rec)).start(
            [QUERY], max_posts_per_query=50, max_charge_usd=Decimal("0.40")
        )
    assert not refused.value.retryable


def test_a_search_the_worker_lost_is_failed_at_full_cost() -> None:
    run = TregPostSearch("tok").get("treg-lost")
    assert (run.status, run.cost_usd) == (SearchStatus.FAILED, None)  # None: settle the whole reservation


def test_a_post_item_becomes_a_normalized_post() -> None:
    post = parse_post(POST_ITEM, QUERY)
    assert post is not None
    assert post.author_url == "https://www.linkedin.com/in/avery-okafor-1234"
    assert post.author_headline == "Head of Growth at Northwind Labs"
    assert post.author_kind == "person"
    assert post.posted_at is not None
    assert post.posted_at.isoformat() == "2026-10-21T19:43:28.091000+00:00"
    assert post.query == QUERY


def test_a_post_date_without_an_offset_is_utc() -> None:
    post = parse_post({**POST_ITEM, "postedAt": {"date": "2026-10-21T19:43:28"}}, QUERY)
    assert post is not None
    assert post.posted_at is not None
    assert post.posted_at.isoformat() == "2026-10-21T19:43:28+00:00"


def test_an_unreadable_post_date_is_left_out_not_fatal() -> None:
    for date_value in ("not a date", 20261021, {"x": 1}):
        post = parse_post({**POST_ITEM, "postedAt": {"date": date_value}}, QUERY)
        assert post is not None
        assert post.posted_at is None


def test_company_posts_reposts_and_empty_items() -> None:
    company = dict(
        POST_ITEM,
        author={"type": "company", "name": "Northwind", "linkedinUrl": "https://www.linkedin.com/company/northwind"},
    )
    parsed = parse_post(company, QUERY)
    assert parsed is not None
    assert (parsed.author_kind, parsed.author_headline) == ("company", None)
    repost = dict(POST_ITEM, content="", repost={"content": "Original text about RevOps Summit"})
    reposted = parse_post(repost, QUERY)
    assert reposted is not None
    assert reposted.text == "Original text about RevOps Summit"
    assert parse_post({"id": "", "content": "no id"}, QUERY) is None
    assert parse_post(dict(POST_ITEM, content=""), QUERY) is None


# ------------------------------------------------------------------------------------------------------ Apollo
APOLLO_PERSON = {
    "id": "6600000000000000000000aa",
    "first_name": "Avery",
    "last_name": "Okafor",
    "name": "Avery Okafor",
    "linkedin_url": "http://www.linkedin.com/in/avery-okafor-1234",
    "title": "Head of Growth",
    "headline": "Head of Growth at Northwind Labs",
    "email": "Avery.Okafor@northwind.example",
    "email_status": "verified",
    "email_domain_catchall": False,
    "seniority": "head",
    "departments": ["master_marketing"],
    "country": "Canada",
    "organization": {
        "name": "Northwind Labs",
        "primary_domain": "northwind.example",
        "industry": "computer software",
        "estimated_num_employees": 180,
    },
}


def test_apollo_bulk_match_keeps_the_order_asked() -> None:
    reply = {"status": "success", "credits_consumed": 1, "matches": [None, APOLLO_PERSON]}
    rec = Recorder({"/api/v1/people/bulk_match": reply})
    urls = ["https://www.linkedin.com/in/nobody", "https://www.linkedin.com/in/avery-okafor-1234"]
    result = ApolloEnrichment("key", transport=httpx2.MockTransport(rec)).match(urls)
    assert result.credits_used == 1
    assert result.people[0] is None
    person = result.people[1]
    assert person is not None
    assert person.email == "avery.okafor@northwind.example"
    assert (person.email_status, person.seniority, person.company_size) == ("verified", "head", 180)
    assert person.linkedin_url == "https://www.linkedin.com/in/avery-okafor-1234"
    request = rec.requests[0]
    assert request.headers["x-api-key"] == "key"
    body = json.loads(request.content)
    assert body["reveal_personal_emails"] is False
    assert body["details"] == [{"linkedin_url": u} for u in urls]


def test_apollo_refuses_more_than_ten_and_skips_empty_batches() -> None:
    enrich = ApolloEnrichment("key", transport=httpx2.MockTransport(Recorder({})))
    with pytest.raises(ValueError, match="at most 10"):
        enrich.match([f"https://www.linkedin.com/in/p{i}" for i in range(11)])
    assert enrich.match([]).credits_used == 0


def test_apollo_rate_limits_are_retryable() -> None:
    rec = Recorder({"/api/v1/people/bulk_match": httpx2.Response(429, json={"error": "rate limited"})})
    with pytest.raises(ProviderError) as exc:
        ApolloEnrichment("key", transport=httpx2.MockTransport(rec)).match(["https://www.linkedin.com/in/x"])
    assert exc.value.retryable


# ---------------------------------------------------------------------------------------------------------- Reoon
def test_reoon_returns_the_status() -> None:
    rec = Recorder({"/api/v1/verify": {"email": "a@northwind.example", "status": "Safe"}})
    assert ReoonVerifier("rkey", transport=httpx2.MockTransport(rec)).verify("a@northwind.example") == "safe"
    assert rec.requests[0].url.params["mode"] == "power"


def test_network_failures_are_retryable() -> None:
    def broken(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("down")

    with pytest.raises(ProviderError) as exc:
        ReoonVerifier("rkey", transport=httpx2.MockTransport(broken)).verify("a@x.example")
    assert exc.value.retryable
    assert exc.value.cost_usd is None  # the request may have got through: what it cost is unknown
    assert "rkey" not in str(exc.value)  # the key never leaks into error messages


@pytest.mark.parametrize(("status", "retryable"), [(408, True), (425, True), (429, True), (503, True), (422, False)])
def test_which_statuses_are_worth_retrying(status: int, retryable: bool) -> None:
    rec = Recorder({"/api/v1/verify": httpx2.Response(status, json={"error": "x"})})
    with pytest.raises(ProviderError) as exc:
        ReoonVerifier("rkey", transport=httpx2.MockTransport(rec)).verify("a@x.example")
    assert exc.value.retryable is retryable
    assert exc.value.cost_usd == 0  # the service answered with an error: nothing was charged
