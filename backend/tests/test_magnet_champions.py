"""A champion report from start to finish, against the made-up market in champion_fakes."""

from collections import Counter
from typing import Any

import pytest

from app.magnet.brain import MOVERS, Customer, Customers, NamedChampion
from app.magnet.build import BuildError
from app.magnet.champions import (
    COMPANY_LOOKUPS,
    HISTORY_LOOKUPS,
    SEARCH_PAGES,
    TREG_CAP_USD,
    WATCH_LOOKUPS,
    ChampionSpec,
    build_champions,
)
from app.magnet.linkedin import COMPANY_SEARCH, HISTORY, LEADS_SEARCH
from tests.champion_fakes import (
    HISTORIES,
    PEOPLE,
    TODAY,
    VENDOR,
    FakeScout,
    history,
    job,
    market,
    mover,
    org,
    page,
    person,
    position,
    tools,
)

SPEC = ChampionSpec(company=VENDOR, website="https://cxhero.example")


def names(rows: list[dict[str, Any]]) -> list[str]:
    return [str(r["name"]) for r in rows]


def test_a_report_names_the_champions_who_moved_graded_and_says_why_the_rest_were_left_out() -> None:
    treg = market()
    scout = FakeScout()
    report = build_champions(SPEC, tools(scout, treg), TODAY)

    assert [(c["name"], c["grade"]) for c in report["champions"]] == [
        ("Moe Moved", "A"),  # named on the site, found by checking where they are now
        ("Dana Named", "A"),  # named on the site, and in the search
        ("Riley Lead", "B"),  # ran CX at a customer for years
        ("Sam Rep", "C"),  # six months as an associate
    ]
    dana = next(c for c in report["champions"] if c["name"] == "Dana Named")
    assert dana["was"]["company"] == "Glowco Inc."
    assert dana["now"]["company"] == "Newbrand"
    assert dana["now"]["industry"] == "Retail"
    assert dana["linkedin"] == person("dana-named")
    assert dana["new"] is True

    assert report["skipped"] == {
        "hidden": 1,
        "duplicate": 1,
        "no_current_role": 1,
        "side_role": 1,
        "joined_vendor": 1,
        "joined_competitor": 1,
        "joined_customer": 1,
        "junior": 1,
        "stale_move": 1,
        "outside_region": 1,
        "non_buyer_industry": 1,
        "not_icp": 1,
        "no_history": 1,
        "not_verified": 1,
        "still_at_customer": 1,
        "left_customer_long_ago": 1,
        "internal_move": 1,
    }
    assert {(w["name"], w["status"]) for w in report["watch"]} == {
        ("Wren Stays", "still_there"),
        ("Kai Nolink", "unchecked"),
    }

    customers = {c["name"]: c for c in report["customers"]}
    assert VENDOR not in customers  # the vendor itself isn't its own customer
    assert customers["Glowco"]["linkedin"] == page("glowco")  # the page in the ICP's industries, not the bigger one
    assert customers["Mugworth"]["linkedin_name"] == "Mugworth Coffee"
    assert customers["Ghost Co"]["linkedin"] == ""  # no page with that name: left out of the search, not guessed

    assert scout.abouts == [MOVERS]  # one screen, told who these people are
    assert len(scout.screened[0]) == 9  # only those who passed the free checks
    stats = report["stats"]
    assert (stats["customers"], stats["matched"], stats["movers"], stats["champions"]) == (5, 4, 20, 4)
    assert stats["grades"] == {"A": 2, "B": 1, "C": 1}
    assert stats["repeat"] is False  # the first report: nobody to compare with
    assert stats["linkedin_usd"] <= TREG_CAP_USD

    (search,) = [q for tool, q, _, _ in treg.calls if tool == LEADS_SEARCH]
    pages = page("glowco") + "," + page("shoebird") + "," + page("mugworth") + "," + page("pillowlane")
    assert search == {
        "pastCompanies": pages,
        "excludeCurrentCompanies": pages,
        "recentlyChangedJobs": "true",
        "pastJobTitles": "Customer Experience,Support",
        "page": "1",
    }


def test_nobody_ruled_out_by_a_free_check_or_the_screen_is_paid_for() -> None:
    treg = market()
    build_champions(SPEC, tools(FakeScout(), treg), TODAY)
    looked_up = {q["profileUrlOrUrn"] for tool, q, _, _ in treg.calls if tool == HISTORY}
    for slug in ("ian-intern", "stu-stale", "lon-don", "lena-law", "vera-vc", "ava-advisor", "cara-customer"):
        assert person(slug) not in looked_up
    assert person("kai-nolink") not in looked_up  # no LinkedIn address on the site: nothing to look up


def test_a_site_with_no_customers_fails_before_anything_is_paid_for() -> None:
    treg = market()
    scout = FakeScout(Customers(customers=[], champions=[], title_keywords=[]))
    with pytest.raises(BuildError, match="doesn't show any customers"):
        build_champions(SPEC, tools(scout, treg), TODAY)
    assert treg.calls == []


def test_customers_with_no_linkedin_page_fail_after_only_the_lookups() -> None:
    treg = market(orgs={})
    with pytest.raises(BuildError, match="LinkedIn page"):
        build_champions(SPEC, tools(FakeScout(), treg), TODAY)
    assert set(treg.tools()) == {COMPANY_SEARCH}


def test_nobody_moved_is_still_a_report() -> None:
    report = build_champions(SPEC, tools(FakeScout(), market(movers=[])), TODAY)
    assert names(report["champions"]) == ["Moe Moved", "Dana Named"]  # the people named on the site who moved
    assert report["stats"]["movers"] == 0


def test_a_people_search_that_fails_keeps_nothing_and_says_so() -> None:
    with pytest.raises(BuildError, match="people search failed"):
        build_champions(SPEC, tools(FakeScout(), market(fail={LEADS_SEARCH})), TODAY)


def test_a_report_built_again_reuses_what_was_paid_for_and_marks_who_is_new() -> None:
    first = build_champions(SPEC, tools(FakeScout(), market()), TODAY)
    newcomer = mover("nia-new", "Nia New", position("Head of Support", "Gumdrop", "Retail", 1))
    treg = market(
        movers=[*PEOPLE, newcomer],
        histories={
            **HISTORIES,
            person("nia-new"): history(
                "nia-new",
                job("Head of Support", "Gumdrop", "gumdrop", (2026, 10), None),
                job("Support Manager", "Shoebird", "shoebird", (2023, 1), (2026, 9)),
            ),
        },
    )
    again = build_champions(ChampionSpec(VENDOR, SPEC.website, before=first), tools(FakeScout(), treg), TODAY)

    searched = [q["search"] for tool, q, _, _ in treg.calls if tool == COMPANY_SEARCH]
    assert searched == ["Ghost Co"]  # the others' pages came from the first report; the one without is tried again
    looked_up = [q["profileUrlOrUrn"] for tool, q, _, _ in treg.calls if tool == HISTORY]
    assert person("riley-lead") not in looked_up  # already a champion: not paid for again
    new = {c["name"]: c["new"] for c in again["champions"]}
    assert new["Nia New"] is True
    assert new["Riley Lead"] is False
    assert again["stats"]["new"] == sum(1 for flag in new.values() if flag)
    assert again["stats"]["repeat"] is True


def test_the_cost_gate_a_huge_market_never_costs_more_than_the_cap() -> None:
    """100 customers, 250 people who all pass every check, 10 named people: the calls stop at their caps and the sum of
    what every call may charge stays under the build's cap."""
    customers = [Customer(name=f"Brand {n}", domain="", evidence="case_study") for n in range(100)]
    champions = [
        NamedChampion(name=f"Named {n}", title="CX Lead", company="Brand 1", linkedin=f"named-{n}") for n in range(10)
    ]
    scout = FakeScout(Customers(customers=customers, champions=champions, title_keywords=["Customer Experience"]))
    orgs = {f"Brand {n}": [org(f"Brand {n}", f"brand-{n}", "Retail")] for n in range(100)}
    crowd = [mover(f"p{n}", f"Person {n}", position("Head of CX", f"Newco {n}", "Retail", 1)) for n in range(250)]
    histories = {
        person(f"p{n}"): history(
            f"p{n}",
            job("Head of CX", f"Newco {n}", f"newco-{n}", (2026, 10), None),
            job("CX Manager", "Brand 1", "brand-1", (2021, 1), (2026, 9)),
        )
        for n in range(250)
    }
    treg = market(orgs=orgs, movers=crowd, histories=histories)

    report = build_champions(SPEC, tools(scout, treg), TODAY)

    per_tool = Counter(treg.tools())
    assert per_tool[COMPANY_SEARCH] <= COMPANY_LOOKUPS
    assert per_tool[LEADS_SEARCH] <= SEARCH_PAGES
    assert per_tool[HISTORY] <= HISTORY_LOOKUPS + WATCH_LOOKUPS
    assert sum(cap for *_, cap in treg.calls) <= TREG_CAP_USD + 1e-9
    assert report["stats"]["linkedin_usd"] <= TREG_CAP_USD
    assert len(scout.screened) == 1  # one screen for everyone
    assert report["skipped"]["over_cap"] == len(scout.screened[0]) - HISTORY_LOOKUPS
    assert report["stats"]["champions"] == HISTORY_LOOKUPS
