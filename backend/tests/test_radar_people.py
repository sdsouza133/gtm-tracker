"""Finding who to write to at a company a refresh added, with treg faked. Every name here is made up."""

from typing import Any

import pytest

from app.models import RoleInHire, Sureness
from app.radar import people
from app.treg import TregError
from tests.treg_fakes import FakeTreg

ACME_PAGE = "https://www.linkedin.com/company/acme"


def profile(name: str, headline: str, slug: str) -> dict[str, Any]:
    return {
        "name": name,
        "position": headline,
        "linkedinUrl": f"https://www.linkedin.com/in/{slug}?trk=search",
        "location": {"linkedinText": "Toronto, ON"},
    }


@pytest.mark.parametrize(
    ("headline", "expected"),
    [
        ("VP, Global RevOps & Enablement at Acme", (RoleInHire.HIRING_MANAGER, Sureness.LIKELY)),
        ("Sales & Revenue Operations Leader | GTM Systems", (RoleInHire.HIRING_MANAGER, Sureness.GUESS)),
        ("Senior GTM Recruiter at Acme", (RoleInHire.RECRUITER, Sureness.LIKELY)),
        ("Co-founder & CEO at Acme", (RoleInHire.FOUNDER, Sureness.LIKELY)),
        ("Founder & CEO at Otherco", None),  # someone else's founder
        ("Senior GTM Consultant at Orama", None),  # works somewhere else
        ("GTM Engineering @ Acme", (RoleInHire.PEER, Sureness.LIKELY)),
        ("VP of Marketing at Acme", (RoleInHire.APPROVER, Sureness.GUESS)),
        ("Executive Assistant", None),
        ("", None),
    ],
)
def test_a_headline_says_what_part_they_play_in_the_hire(
    headline: str, expected: tuple[RoleInHire, Sureness] | None
) -> None:
    assert people.guess(headline, "Acme") == expected


def test_people_are_found_a_title_word_at_a_time_and_the_most_useful_kept() -> None:
    by_word = {
        "GTM": [
            profile("Ana Example", "GTM Engineering @ Acme", "ana"),
            profile("Orla Example", "Senior GTM Consultant at Orama", "orla"),
            profile("Rae Example", "Senior GTM Recruiter at Acme", "rae"),
        ],
        "revenue operations": [
            profile("Val Example", "VP, Global RevOps & Enablement at Acme", "val"),
            profile("Ana Example", "GTM Engineering @ Acme", "ana"),  # found twice, kept once
            profile("Rex Example", "Technical Recruiter at Acme", "rex"),
        ],
        "growth": [profile("Gus Example", "VP of Marketing at Acme", "gus")],
    }
    treg = FakeTreg({people.PROFILE_SEARCH: lambda q, _b: {"elements": by_word[q["title"]]}}, price=0.002)
    found, spent = people.find(treg, ACME_PAGE, "Acme", 200, 4, max_usd=1.0)
    assert [(p.name, p.role) for p in found] == [
        ("Val Example", RoleInHire.HIRING_MANAGER),
        ("Rae Example", RoleInHire.RECRUITER),  # one recruiter is enough
        ("Gus Example", RoleInHire.APPROVER),
        ("Ana Example", RoleInHire.PEER),
    ]
    assert found[0].linkedin == "https://www.linkedin.com/in/val"  # without LinkedIn's tracking
    assert found[0].location == "Toronto, ON"
    assert spent == pytest.approx(0.006)
    assert [q["title"] for _, q, _, _ in treg.calls] == ["GTM", "revenue operations", "growth"]
    assert all(q["currentCompany"] == ACME_PAGE for _, q, _, _ in treg.calls)
    assert all(cap == pytest.approx(people.CALL_USD) for *_, cap in treg.calls)


def test_a_small_team_is_searched_for_its_founder_first() -> None:
    treg = FakeTreg({people.PROFILE_SEARCH: {"elements": []}})
    people.find(treg, ACME_PAGE, "Acme", 12, 4, max_usd=1.0)
    assert [q["title"] for _, q, _, _ in treg.calls] == ["founder", "GTM", "growth"]


def test_no_call_is_made_that_the_budget_left_cant_cover_and_a_failed_word_is_skipped() -> None:
    treg = FakeTreg({people.PROFILE_SEARCH: {"elements": []}}, price=0.002)
    people.find(treg, ACME_PAGE, "Acme", 200, 4, max_usd=0.005)
    assert len(treg.calls) == 1  # $0.002 spent; a second call lists at $0.004: over the $0.005 left

    def busy_on_ops(query: dict[str, Any], _body: Any) -> dict[str, Any]:
        if query["title"] == "revenue operations":
            raise TregError("busy", retryable=True)
        return {"elements": [profile("Ana Example", "GTM Engineering @ Acme", "ana")]}

    found, _ = people.find(FakeTreg({people.PROFILE_SEARCH: busy_on_ops}), ACME_PAGE, "Acme", 200, 4, max_usd=1.0)
    assert [p.name for p in found] == ["Ana Example"]
