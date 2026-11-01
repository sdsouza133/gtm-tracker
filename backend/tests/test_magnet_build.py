from datetime import date
from typing import Any

import pytest

from app.enrich.apollo import ApolloError
from app.magnet import linkedin as li
from app.magnet.build import PLANS, BuildError, Spec, Tools, build
from app.magnet.linkedin import LinkedIn
from tests.magnet_fakes import (
    ORGS,
    P1,
    P2,
    P3,
    R1,
    RIA,
    RIVAL_PAGE,
    FakeApollo,
    FakeBrain,
    FakeRunner,
    post,
    runner,
    site,
)

TODAY = date(2026, 11, 1)


def tools(run: FakeRunner, apollo: FakeApollo | None = None, brain: FakeBrain | None = None) -> Tools:
    return Tools(
        read_site=site,
        brain=brain or FakeBrain("rivalco.example", "nolinkedin.example", "otherco.example"),
        linkedin=LinkedIn(run),
        apollo=apollo or FakeApollo(ORGS),
    )


def spec(mode: str = "teaser", competitors: tuple[str, ...] = ()) -> Spec:
    return Spec(mode=mode, company="Prospect", website="https://prospect.example", competitors=competitors)  # type: ignore[arg-type]


def test_a_teaser_reads_one_competitor_and_ranks_people_in_the_icp_by_touchpoints() -> None:
    run = runner()
    apollo = FakeApollo(ORGS, emails={"https://www.linkedin.com/in/ana-example": "ana@buyer.example"})
    steps: list[str] = []
    report = build(spec(), tools(run, apollo), TODAY, lambda step, _: steps.append(step))

    assert [c["name"] for c in report["competitors"]] == ["RivalCo"]
    assert report["competitors"][0]["linkedin"] == RIVAL_PAGE
    assert report["competitors"][0]["posts"] == [P2, P1, P3]  # most engaged first; the post nobody touched is skipped
    leads = report["leads"]
    assert [(lead["name"], lead["tier"], lead["country"]) for lead in leads] == [
        ("Ana Example", "hot", "US"),  # two likes and a comment, across two posts
        ("Gus Example", "warm", "CA"),  # one comment
        ("Ben Example", "warm", "US"),  # two likes
    ]
    ana = leads[0]
    assert ana["said"] == ["Great point"]
    assert ana["linkedin"] == "https://www.linkedin.com/in/ana-example"
    assert ana["competitors"] == ["RivalCo"]
    assert "email" not in ana  # a teaser spends no Apollo credits on emails
    assert apollo.matched == []
    stats = report["stats"]
    assert stats["people"] == 7  # Ana, Ben, Cal, Dee, Eve, Fay, Gus; the company page isn't a person
    assert stats["after_rules"] == 5  # the recruiter and RivalCo's own seller are dropped before Claude sees them
    assert stats["fit"] == 4  # Ana, Gus, Ben and Eve; the designer isn't a buyer
    assert stats["in_region"] == 3  # Eve is in the UK
    assert steps[0] == "reading the website"
    assert "finding work emails" not in steps


def test_a_teaser_stays_inside_its_budget() -> None:
    run = runner()
    report = build(spec(), tools(run), TODAY)
    assert sum(cap for _, _, cap in run.runs) <= PLANS["teaser"].budget_usd
    assert report["stats"]["apify_usd"] <= PLANS["teaser"].budget_usd
    assert li.PROFILE_POSTS not in run.actors()  # no decision makers in a teaser


def test_the_full_build_reads_three_competitors_and_their_decision_makers_and_finds_emails() -> None:
    run = runner()
    ria = {
        "id": "apollo-ria",
        "name": "Ria Example",
        "title": "CEO",
        "linkedin_url": "http://www.linkedin.com/in/ria-example",
    }
    apollo = FakeApollo(
        ORGS,
        emails={"https://www.linkedin.com/in/ana-example": "ana@buyer.example"},
        people={"rivalco.example": [ria]},
    )
    report = build(spec("full"), tools(run, apollo), TODAY)

    assert [c["name"] for c in report["competitors"]] == ["RivalCo", "OtherCo"]  # NoPage has no LinkedIn page
    assert report["competitors"][0]["people"] == [{"name": "Ria Example", "title": "CEO", "linkedin": RIA}]
    assert R1 in report["competitors"][0]["posts"]  # the CEO's own post is mined too
    by_name = {lead["name"]: lead for lead in report["leads"]}
    assert by_name["Ana Example"]["competitors"] == ["OtherCo", "RivalCo"]
    assert by_name["Ana Example"]["email"] == "ana@buyer.example"
    assert by_name["Ana Example"]["email_status"] == "verified"
    assert "Hal Example" in by_name  # liked the CEO's post
    assert report["stats"]["emails"] == {"asked": len(report["leads"]), "found": 1, "error": ""}
    assert sum(cap for _, _, cap in run.runs) <= PLANS["full"].budget_usd


def test_the_competitors_the_user_names_go_first() -> None:
    brain = FakeBrain("rivalco.example")
    report = build(spec("teaser", ("otherco.example",)), tools(runner(), brain=brain), TODAY)
    assert brain.hints == [["otherco.example"]]
    assert [c["name"] for c in report["competitors"]] == ["OtherCo"]


def test_the_prospect_itself_is_never_a_competitor() -> None:
    orgs = {
        **ORGS,
        "prospect.example": {"name": "Prospect", "linkedin_url": "https://www.linkedin.com/company/prospect"},
    }
    brain = FakeBrain("prospect.example", "rivalco.example")
    report = build(spec(), tools(runner(), FakeApollo(orgs), brain), TODAY)
    assert [c["name"] for c in report["competitors"]] == ["RivalCo"]


def test_no_competitor_on_linkedin_is_a_clear_error() -> None:
    with pytest.raises(BuildError, match="LinkedIn page"):
        build(spec(), tools(runner(), FakeApollo({})), TODAY)


def test_no_recent_posts_is_a_clear_error() -> None:
    with pytest.raises(BuildError, match="last month"):
        build(spec(), tools(runner(posts=[])), TODAY)


def test_one_post_failing_leaves_the_rest_but_all_failing_is_an_error() -> None:
    run = runner()
    calls = {"n": 0}
    real = run.run

    def flaky(actor: str, actor_input: dict[str, Any], max_usd: float, *, partial_ok: bool = False) -> Any:
        if actor == li.REACTIONS:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("timeout")
        return real(actor, actor_input, max_usd, partial_ok=partial_ok)

    run.run = flaky  # type: ignore[method-assign]
    report = build(spec(), tools(run), TODAY)
    assert report["stats"]["posts_failed"] == 1
    assert report["leads"]

    with pytest.raises(BuildError, match="likes and comments"):
        build(spec(), tools(runner(fail={li.REACTIONS})), TODAY)


def test_an_apollo_error_stops_the_email_lookups_and_says_why() -> None:
    class Broke(FakeApollo):
        def match(self, **_: Any) -> dict[str, Any] | None:
            raise ApolloError("Apollo 422: insufficient credits")

    report = build(spec("full"), tools(runner(), Broke(ORGS)), TODAY)
    assert report["stats"]["emails"]["asked"] == 1
    assert "credits" in report["stats"]["emails"]["error"]
    assert report["leads"]  # the leads are still there, without emails


def test_the_decision_makers_posts_failing_still_leaves_the_company_pages() -> None:
    ria = {"id": "apollo-ria", "name": "Ria Example", "linkedin_url": "http://www.linkedin.com/in/ria-example"}
    apollo = FakeApollo(ORGS, people={"rivalco.example": [ria]})
    report = build(spec("full"), tools(runner(fail={li.PROFILE_POSTS}), apollo), TODAY)
    assert R1 not in report["competitors"][0]["posts"]
    assert report["leads"]


def test_a_post_is_matched_to_its_author_even_without_the_query_echoed_back() -> None:
    bare = post(R1, RIA, likes=3, comments=0)
    del bare["query"]
    bare["author"] = {
        "linkedinUrl": "https://www.linkedin.com/in/ria-example?miniProfileUrn=urn%3Ali%3Afs_miniProfile%3A1"
    }
    ria = {"id": "apollo-ria", "name": "Ria Example", "linkedin_url": "http://www.linkedin.com/in/ria-example"}
    report = build(
        spec("full"), tools(runner(people_posts=[bare]), FakeApollo(ORGS, people={"rivalco.example": [ria]})), TODAY
    )
    assert R1 in report["competitors"][0]["posts"]


def test_recruiters_are_kept_for_a_prospect_that_sells_to_recruiters() -> None:
    class SellsToRecruiters(FakeBrain):
        def icp(self, site: dict[str, Any], competitors: list[str]) -> Any:
            found = super().icp(site, competitors)
            found.titles = ["Head of Talent Acquisition", "Recruiting Manager"]
            return found

    brain = SellsToRecruiters("rivalco.example")
    build(spec(), tools(runner(), brain=brain), TODAY)
    assert "Technical Recruiter" in brain.screened[0]  # Claude judges them instead of the rule dropping them
    assert "Account Executive at RivalCo" not in brain.screened[0]  # the competitor's own staff still go
