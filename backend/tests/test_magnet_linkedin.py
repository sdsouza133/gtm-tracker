from datetime import date
from typing import Any

import httpx2
import pytest

from app.magnet import linkedin as li
from app.magnet.linkedin import LinkedIn, LinkedInError, Post, parse_post, parse_profile
from tests.magnet_fakes import RIVAL_PAGE, FakeRunner, comment, company_reaction, post, profile, reaction

P1 = "https://www.linkedin.com/posts/rivalco_p1"


def a_post(likes: int = 10, comments: int = 2) -> Post:
    found = parse_post(post(P1, RIVAL_PAGE, likes, comments))
    assert found is not None
    return found


def test_posts_are_read_with_their_engagement_and_whose_page_they_came_from() -> None:
    p = a_post()
    assert (p.target, p.day, p.likes, p.comments, p.weight) == (RIVAL_PAGE, date(2026, 10, 28), 10, 2, 16)
    assert parse_post({"type": "article", "linkedinUrl": P1}) is None


def test_engagers_are_people_only_and_capped_by_the_budget() -> None:
    runner = FakeRunner(
        reactions={P1: [reaction("ACoAAana", "Ana E.", "VP Sales", P1), company_reaction(P1)]},
        comments={P1: [comment("ACoAAben", "ben-example", "Head of RevOps", P1, "Great point")]},
    )
    found, spent = LinkedIn(runner).engagers(a_post(), reactions=30, comments=15, max_usd=1.0)
    assert [(e.key, e.kind) for e in found] == [("ACoAAana", "reaction"), ("ACoAAben", "comment")]
    assert found[1].text == "Great point"
    assert found[1].day == date(2026, 10, 29)
    assert found[0].day == date(2026, 10, 28)  # a like has no date; the post's stands in
    assert spent == pytest.approx(3 * 0.002)  # three items came back, the company too
    (_, r_input, r_cap), (_, _, c_cap) = runner.runs
    assert r_input == {"posts": [P1], "maxItems": 30}
    assert r_cap == pytest.approx(10 * 0.002 * li.CAP_SLACK + 0.01)  # only 10 likes to read
    assert c_cap == pytest.approx(2 * 0.002 * li.CAP_SLACK + 0.01)


def test_a_post_nobody_engaged_with_costs_nothing() -> None:
    runner = FakeRunner()
    assert LinkedIn(runner).engagers(a_post(0, 0), 30, 15, 1.0) == ([], 0.0)
    assert runner.runs == []


def test_no_budget_left_means_no_run() -> None:
    runner = FakeRunner()
    assert LinkedIn(runner).posts([RIVAL_PAGE], 5, max_usd=0.0) == ([], 0.0)
    assert runner.runs == []


def test_a_failed_run_is_a_linkedin_error() -> None:
    with pytest.raises(LinkedInError, match="linkedin-post-reactions"):
        LinkedIn(FakeRunner(fail={li.REACTIONS})).engagers(a_post(), 30, 15, 1.0)


def test_profiles_give_the_public_url_country_and_current_job() -> None:
    runner = FakeRunner(profiles=[profile("ACoAAana", "ana-example", "us", "VP Sales", "Buyer Inc")])
    found, _ = LinkedIn(runner).profiles(["https://www.linkedin.com/in/ACoAAana"], 1.0)
    p = found["ACoAAana"]
    assert (p.url, p.name, p.country, p.title, p.company) == (
        "https://www.linkedin.com/in/ana-example",
        "Ana Example",
        "US",
        "VP Sales",
        "Buyer Inc",
    )
    assert runner.runs[0][1]["profileScraperMode"] == li.PROFILE_MODE
    assert parse_profile({"firstName": "No", "lastName": "Id"}) is None


def test_a_run_never_costs_more_than_the_budget_left() -> None:
    runner = FakeRunner(reactions={P1: [reaction(f"ACoAA{n}", "X", "VP Sales", P1) for n in range(40)]})
    LinkedIn(runner).engagers(a_post(likes=40, comments=0), reactions=30, comments=15, max_usd=0.05)
    assert runner.runs[0][1]["maxItems"] == 25  # $0.05 buys 25 likes, not 30
    assert runner.runs[0][2] <= 0.05

    runner = FakeRunner()
    assert LinkedIn(runner).engagers(a_post(), 30, 15, max_usd=0.04) == ([], 0.0)  # under Apify's minimum cap
    assert LinkedIn(runner).profiles(["https://www.linkedin.com/in/ACoAAana"], max_usd=0.04) == ({}, 0.0)
    assert runner.runs == []


def test_a_run_that_failed_with_nothing_saved_is_an_error_but_a_stopped_one_keeps_its_items() -> None:
    with pytest.raises(LinkedInError, match="ended FAILED"):
        LinkedIn(FakeRunner(status="FAILED")).engagers(a_post(), 30, 15, 1.0)
    stopped = FakeRunner(status="ABORTED", reactions={P1: [reaction("ACoAAana", "Ana E.", "VP Sales", P1)]})
    found, _ = LinkedIn(stopped).engagers(a_post(comments=0), 30, 15, 1.0)
    assert [e.key for e in found] == ["ACoAAana"]


def test_a_timeout_is_a_linkedin_error() -> None:
    class Slow(FakeRunner):
        def run(self, *_: Any, **__: Any) -> Any:
            raise httpx2.ReadTimeout("slow", request=httpx2.Request("GET", "https://api.apify.com/v2/x"))

    with pytest.raises(LinkedInError, match="ReadTimeout"):
        LinkedIn(Slow()).posts([RIVAL_PAGE], 5, 1.0)


def test_what_a_failed_run_cost_is_still_counted() -> None:
    with pytest.raises(LinkedInError) as failed:
        LinkedIn(FakeRunner(status="FAILED", charged=0.03)).engagers(a_post(), 30, 15, 1.0)
    assert failed.value.spent == pytest.approx(0.03)

    likes = [reaction(f"ACoAA{n}", "X", "VP Sales", P1) for n in range(10)]
    with pytest.raises(LinkedInError) as comments_failed:
        LinkedIn(FakeRunner(reactions={P1: likes}, fail={li.COMMENTS})).engagers(a_post(), 30, 15, 1.0)
    assert comments_failed.value.spent == pytest.approx(10 * 0.002)  # the likes read before the comments failed
