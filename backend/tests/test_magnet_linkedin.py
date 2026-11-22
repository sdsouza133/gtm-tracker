from datetime import date
from typing import Any

import pytest

from app.magnet import linkedin as li
from app.magnet.linkedin import LinkedIn, LinkedInError, Post, parse_post, parse_profile
from app.treg import Answer, TregError
from tests.champion_fakes import TODAY, history, job, market, mover, org, person, position
from tests.magnet_fakes import OTHER_PAGE, RIVAL_PAGE, FakeHarvest, comment, company_reaction, post, profile, reaction
from tests.treg_fakes import FakeTreg

P1 = "https://www.linkedin.com/posts/rivalco_p1"


def a_post(likes: int = 10, comments: int = 2) -> Post:
    found = parse_post(post(P1, RIVAL_PAGE, likes, comments), RIVAL_PAGE)
    assert found is not None
    return found


def test_posts_are_read_with_their_engagement_and_whose_page_they_came_from() -> None:
    p = a_post()
    assert (p.target, p.day, p.likes, p.comments, p.weight) == (RIVAL_PAGE, date(2026, 10, 28), 10, 2, 16)
    assert parse_post({"type": "article", "linkedinUrl": P1}, RIVAL_PAGE) is None


def test_posts_are_read_per_page_and_person() -> None:
    harvest = FakeHarvest(posts=[post(P1, RIVAL_PAGE, 10, 2), post(f"{P1}-2", RIVAL_PAGE, 3, 0)])
    found, spent = LinkedIn(harvest).posts([RIVAL_PAGE], 1, max_usd=1.0)
    assert [p.url for p in found] == [P1]  # newest first, as many as asked for
    assert spent == pytest.approx(0.002)
    assert harvest.calls == [(li.COMPANY_POSTS, {"company": RIVAL_PAGE, "postedLimit": "month", "page": "1"}, 0.004)]


def test_only_posts_since_the_date_asked_for_are_kept() -> None:
    old = post(f"{P1}-old", RIVAL_PAGE, 90, 9, day="2026-08-02")  # a person's feed comes back from months ago too
    harvest = FakeHarvest(people_posts=[post(P1, RIVAL_PAGE, 10, 2), old])
    found, spent = LinkedIn(harvest).posts([RIVAL_PAGE], 5, max_usd=1.0, people=True, since=date(2026, 10, 1))
    assert [p.url for p in found] == [P1]
    assert spent == pytest.approx(0.002)  # the page was paid for either way


def test_engagers_are_people_only() -> None:
    harvest = FakeHarvest(
        reactions={P1: [reaction("ACoAAana", "Ana E.", "VP Sales", P1), company_reaction(P1)]},
        comments={P1: [comment("ACoAAben", "ben-example", "Head of RevOps", P1, "Great point")]},
    )
    found, spent = LinkedIn(harvest).engagers(a_post(), reactions=30, comments=15, max_usd=1.0)
    assert [(e.key, e.kind) for e in found] == [("ACoAAana", "reaction"), ("ACoAAben", "comment")]
    assert found[1].text == "Great point"
    assert found[1].day == date(2026, 10, 29)
    assert found[0].day == date(2026, 10, 28)  # a like has no date; the post's stands in
    assert spent == pytest.approx(2 * 0.002)  # one page of likes, one of comments
    assert harvest.tools() == [li.REACTIONS, li.COMMENTS]


def test_more_likes_than_a_page_are_read_page_by_page() -> None:
    likes = [reaction(f"ACoAA{n}", "X", "VP Sales", P1) for n in range(40)]
    harvest = FakeHarvest(reactions={P1: likes}, page_size=10)
    found, spent = LinkedIn(harvest).engagers(a_post(likes=40, comments=0), reactions=25, comments=15, max_usd=1.0)
    assert len(found) == 25
    assert [q["page"] for _, q, _ in harvest.calls] == ["1", "2", "3"]
    assert spent == pytest.approx(3 * 0.002)


def test_a_post_nobody_engaged_with_costs_nothing() -> None:
    harvest = FakeHarvest()
    assert LinkedIn(harvest).engagers(a_post(0, 0), 30, 15, 1.0) == ([], 0.0)
    assert harvest.calls == []


def test_no_call_is_made_that_the_budget_left_cant_cover() -> None:
    harvest = FakeHarvest(reactions={P1: [reaction(f"ACoAA{n}", "X", "VP Sales", P1) for n in range(40)]})
    assert LinkedIn(harvest).posts([RIVAL_PAGE], 5, max_usd=0.0) == ([], 0.0)
    assert LinkedIn(harvest).engagers(a_post(), 30, 15, max_usd=0.003) == ([], 0.0)  # a call lists at $0.004
    assert LinkedIn(harvest).profiles(["https://www.linkedin.com/in/ACoAAana"], max_usd=0.003) == ({}, 0.0)
    assert harvest.calls == []
    found, _ = LinkedIn(harvest).engagers(a_post(likes=40), 30, 15, max_usd=0.005)  # likes, but no room for comments
    assert harvest.tools() == [li.REACTIONS]
    assert len(found) == 30
    assert all(cap == pytest.approx(li.PRICE[tool]) for tool, _, cap in harvest.calls)  # each call capped at its price


def test_profiles_give_the_public_url_country_and_current_job() -> None:
    harvest = FakeHarvest(profiles=[profile("ACoAAana", "ana-example", "us", "VP Sales", "Buyer Inc")])
    found, spent = LinkedIn(harvest).profiles(
        ["https://www.linkedin.com/in/ACoAAana", "https://www.linkedin.com/in/nobody-example"], 1.0
    )
    assert list(found) == ["ACoAAana"]  # a profile that isn't found is left out
    p = found["ACoAAana"]
    assert (p.url, p.name, p.country, p.title, p.company) == (
        "https://www.linkedin.com/in/ana-example",
        "Ana Example",
        "US",
        "VP Sales",
        "Buyer Inc",
    )
    asked = sorted((q.get("profileId") or q.get("url"), q["main"]) for _, q, _ in harvest.calls)
    assert asked == [("ACoAAana", "true"), ("https://www.linkedin.com/in/nobody-example", "true")]
    assert spent == pytest.approx(2 * 0.002)
    assert parse_profile({"firstName": "No", "lastName": "Id"}) is None


def test_profiles_failing_one_by_one_are_left_out_but_all_failing_is_an_error() -> None:
    class Flaky(FakeHarvest):
        def call(
            self, tool: str, *, query: dict[str, Any] | None = None, body: dict[str, Any] | None = None, max_usd: float
        ) -> Answer:
            if "ACoAAben" in str(query):
                raise TregError("busy", retryable=True)
            return super().call(tool, query=query, body=body, max_usd=max_usd)

    harvest = Flaky(profiles=[profile("ACoAAana", "ana-example", "US")])
    urls = ["https://www.linkedin.com/in/ACoAAana", "https://www.linkedin.com/in/ACoAAben"]
    found, _ = LinkedIn(harvest).profiles(urls, 1.0)
    assert list(found) == ["ACoAAana"]
    with pytest.raises(LinkedInError, match="busy"):
        LinkedIn(harvest).profiles(urls[1:], 1.0)


def test_a_failed_call_is_a_linkedin_error_that_keeps_what_was_paid_for() -> None:
    with pytest.raises(LinkedInError, match=r"post\.reactions"):
        LinkedIn(FakeHarvest(fail={li.REACTIONS})).engagers(a_post(), 30, 15, 1.0)

    likes = [reaction(f"ACoAA{n}", "X", "VP Sales", P1) for n in range(10)]
    with pytest.raises(LinkedInError) as comments_failed:
        LinkedIn(FakeHarvest(reactions={P1: likes}, fail={li.COMMENTS})).engagers(a_post(), 30, 15, 1.0)
    assert comments_failed.value.spent == pytest.approx(0.002)  # the likes' page; treg doesn't bill a failed call
    assert len(comments_failed.value.found) == 10  # the likes read before the comments failed are kept


@pytest.mark.parametrize("failing", [li.REACTIONS, li.COMMENTS])
def test_pages_read_before_a_later_page_fails_are_kept(failing: str) -> None:
    class SecondPageFails(FakeHarvest):
        def call(
            self, tool: str, *, query: dict[str, Any] | None = None, body: dict[str, Any] | None = None, max_usd: float
        ) -> Answer:
            if tool == failing and (query or {}).get("page") == "2":
                self.calls.append((tool, dict(query or {}), max_usd))
                raise TregError("busy", retryable=True)
            return super().call(tool, query=query, body=body, max_usd=max_usd)

    likes = [reaction(f"ACoAAl{n}", "X", "VP Sales", P1) for n in range(15)]
    notes = [comment(f"ACoAAc{n}", f"c-{n}", "Head of RevOps", P1, "Agreed") for n in range(15)]
    harvest = SecondPageFails(reactions={P1: likes}, comments={P1: notes}, page_size=10)
    with pytest.raises(LinkedInError, match="busy") as failed:
        LinkedIn(harvest).engagers(a_post(likes=15, comments=15), 30, 30, 1.0)
    kinds = [e.kind for e in failed.value.found]
    if failing == li.REACTIONS:
        assert kinds == ["reaction"] * 10  # the first page of likes, paid for and kept
        assert failed.value.spent == pytest.approx(0.002)
    else:
        assert kinds == ["reaction"] * 15 + ["comment"] * 10  # every like, and the first page of comments
        assert failed.value.spent == pytest.approx(3 * 0.002)


def test_posts_read_before_a_later_target_fails_are_kept() -> None:
    class SecondTargetFails(FakeHarvest):
        def call(
            self, tool: str, *, query: dict[str, Any] | None = None, body: dict[str, Any] | None = None, max_usd: float
        ) -> Answer:
            if (query or {}).get("company") == OTHER_PAGE:
                raise TregError("busy", retryable=True)
            return super().call(tool, query=query, body=body, max_usd=max_usd)

    harvest = SecondTargetFails(posts=[post(P1, RIVAL_PAGE, 10, 2), post(f"{P1}-2", RIVAL_PAGE, 3, 0)])
    with pytest.raises(LinkedInError, match="busy") as failed:
        LinkedIn(harvest).posts([RIVAL_PAGE, OTHER_PAGE], 5, max_usd=1.0)
    assert [p.url for p in failed.value.posts] == [P1, f"{P1}-2"]  # the first page's posts, paid for and kept
    assert failed.value.spent == pytest.approx(0.002)


def test_a_dropped_connection_counts_its_whole_ceiling() -> None:
    class Dropped(FakeHarvest):
        def call(
            self,
            tool: str,  # noqa: ARG002
            *,
            query: dict[str, Any] | None = None,  # noqa: ARG002
            body: dict[str, Any] | None = None,  # noqa: ARG002
            max_usd: float,
        ) -> Answer:
            raise TregError("couldn't reach treg", spent=max_usd, retryable=True)

    with pytest.raises(LinkedInError, match="couldn't reach") as dropped:
        LinkedIn(Dropped()).posts([RIVAL_PAGE], 5, 1.0)
    assert dropped.value.spent == pytest.approx(0.004)


# ----------------------------------------------------------------------------- champion reports


def orgs(*items: dict[str, Any]) -> list[li.Org]:
    return [o for o in (li.parse_org(i) for i in items) if o]


@pytest.mark.parametrize(
    ("name", "candidates", "industries", "picked"),
    [
        ("Thrive", [org("Thrive Inc.", "thrive", "Retail")], [], "thrive"),  # an Inc. aside
        ("HexClad", [org("HexClad Cookware", "hexclad", "Manufacturing")], [], "hexclad"),  # the name plus a word
        ("Ghost Co", [org("Ghostly Labs", "ghostly", "Software")], [], None),  # a longer word isn't the name
        ("Bobbie", [org("Evelyn & Bobbie", "eb", "Retail")], [], None),  # the name has to come first
        ("Acme", [org("Acme Widgets Global Holdings Group", "acme-big", "Retail")], [], None),  # too many extra words
        (
            "Dossier",
            [
                org("Dossier", "dossier-media", "Media", "18K followers"),
                org("Dossier Perfumes", "dossierp", "Personal Care Product Manufacturing", "24K followers"),
            ],
            ["Personal care"],
            "dossierp",  # in the ICP's industries beats the exact name elsewhere
        ),
        (
            "Glowco",
            [org("Glowco", "glowco-1", "Retail", "2K followers"), org("Glowco", "glowco-2", "Retail", "9K followers")],
            [],
            "glowco-2",
        ),
        ("", [org("Anything", "any", "Retail")], [], None),
    ],
)
def test_a_customer_is_matched_to_its_page_or_to_none(
    name: str, candidates: list[dict[str, Any]], industries: list[str], picked: str | None
) -> None:
    got = li.pick_company(name, orgs(*candidates), industries)
    assert (got.linkedin.rsplit("/", 1)[-1] if got else None) == picked


def test_company_lookups_stop_at_what_the_budget_pays_for() -> None:
    treg = FakeTreg({li.COMPANY_SEARCH: {"elements": [org("Brand", "brand", "Retail")]}}, price=0.002)
    found, spent = LinkedIn(treg).companies(
        ["Brand", "Brand", "Other", "Third"], [], max_usd=li.PRICE[li.COMPANY_SEARCH] * 2
    )
    # each name once, two calls paid for (in either order: the searches run side by side)
    assert sorted(q["search"] for _, q, _, _ in treg.calls) == ["Brand", "Other"]
    assert all(cap == li.PRICE[li.COMPANY_SEARCH] for *_, cap in treg.calls)
    assert set(found) == {"Brand"}  # "Other" got a page named Brand: not its page
    assert spent == pytest.approx(0.004)


def test_the_people_search_asks_for_movers_from_the_customers_and_reads_them() -> None:
    people = [
        mover("a", "Ann Able", position("Head of CX", "Newco", "Retail", 14)),
        {"id": "id-x", "firstName": "LinkedIn", "lastName": "Member", "currentPositions": []},
        {
            "id": "id-y",
            "linkedinUrl": person("y"),
            "firstName": "Yu",
            "lastName": "Why",
            "currentPositions": [
                {
                    "title": "VP Support",
                    "companyName": "Urnco",
                    "company": {"entityUrn": "urn:li:fs_salesCompany:4242", "industry": "Retail"},
                }
            ],
        },
    ]
    treg = market(movers=people)
    found, total, _ = LinkedIn(treg).movers(["https://www.linkedin.com/company/glowco"], ["CX"], want=75, max_usd=0.30)
    (call,) = treg.calls
    assert call[1]["recentlyChangedJobs"] == "true"
    assert call[1]["pastJobTitles"] == "CX"
    assert call[1]["excludeCurrentCompanies"] == call[1]["pastCompanies"]
    assert total == 3
    ann, member, yu = found
    assert (ann.name, ann.jobs[0].months, ann.jobs[0].industry, ann.hidden) == ("Ann Able", 14, "Retail", False)
    assert member.hidden
    assert yu.jobs[0].company_linkedin == "https://www.linkedin.com/company/4242"  # from the URN when there's no link


def test_no_title_words_means_no_title_filter() -> None:
    treg = market(movers=[])
    LinkedIn(treg).movers(["https://www.linkedin.com/company/glowco"], [], want=25, max_usd=0.10)
    assert "pastJobTitles" not in treg.calls[0][1]


def test_a_work_history_reads_either_shape_newest_first() -> None:
    body = history(
        "kim",
        job("CX Manager", "Glowco Inc.", "glowco", (2020, 1), (2023, 6)),
        job("Head of CX", "Newco", "newco", (2026, 10), None),
    )
    for shape in (body, {"output": {}, "raw": body}):
        parsed = li.parse_history(shape, TODAY)
        assert parsed.url == person("kim")
        assert [j.title for j in parsed.jobs] == ["Head of CX", "CX Manager"]
        assert parsed.jobs[0].end is None
        assert parsed.jobs[0].months == 1
        assert parsed.jobs[1].start == date(2020, 1, 1)
        assert parsed.jobs[1].months == 41


def test_work_histories_stay_in_budget_and_only_all_failing_is_an_error() -> None:
    treg = market()
    urls = [person(f"p{n}") for n in range(5)]
    _, spent = LinkedIn(treg).history(urls, max_usd=li.PRICE[li.HISTORY] * 3, today=TODAY)
    assert len(treg.calls) == 3
    assert spent == pytest.approx(0.0045)
    with pytest.raises(LinkedInError):
        LinkedIn(market(fail={li.HISTORY})).history(urls, max_usd=1.0, today=TODAY)
