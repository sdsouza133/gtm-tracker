"""The paid searches, with treg faked."""

from datetime import UTC, date, datetime, timedelta

import pytest

from app.radar.fit import RadarConfig
from app.radar.sources import (
    GOOGLE_SEARCH,
    JOB_DETAILS,
    LINKEDIN_JOBS,
    POST_SEARCH,
    parse_job,
    search_ats,
    search_linkedin,
    search_params,
    search_posts,
    window_seconds,
)
from tests.radar_fakes import FakeWeb, ashby, ashby_job, job_details, linkedin_item
from tests.treg_fakes import FakeTreg, pages

UUID_FIT = "dddddddd-dddd-dddd-dddd-dddddddddddd"
UUID_OLD = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"


def test_job_boards_found_through_google_are_read_from_the_board() -> None:
    def google(_query: object, body: dict[str, str] | None) -> dict[str, object]:
        assert body is not None
        if body["q"] != 'site:jobs.ashbyhq.com "GTM Engineer"':
            return {"organic": []}
        assert body["tbs"] == "qdr:d2"  # the last two days
        return {
            "organic": [
                {"link": f"https://jobs.ashbyhq.com/acme/{UUID_FIT}"},
                {"link": "https://example.com/nothing"},
                {"link": f"https://jobs.ashbyhq.com/acme/{UUID_OLD}"},
            ]
        }

    web = FakeWeb(
        json_by_url=ashby(
            "acme",
            ashby_job(
                "GTM Engineer", UUID_FIT, posted="2026-10-24", compensation={"compensationTierSummary": "$150K – $170K"}
            ),
            ashby_job("GTM Engineer", UUID_OLD, posted="2026-09-01"),
            ashby_job("GTM Engineer", "not-in-the-search", posted="2026-10-24"),
        )
    )
    treg = FakeTreg({GOOGLE_SEARCH: google})
    found = search_ats(treg, web, RadarConfig(keywords=["GTM Engineer"]), days=2, today=date(2026, 10, 26))
    assert [j["job_id"] for j in found.jobs] == [UUID_FIT]  # only searched postings, only recent ones
    job = found.jobs[0]
    assert (job["company"], job["source"], job["board"], job["salary"]) == (
        "Acme",
        "ashby board",
        {"ats": "ashby", "slug": "acme"},
        "$150K – $170K",
    )
    assert (found.meta["boards"], found.meta["read"], found.meta["kept"]) == (1, 2, 1)
    assert len(treg.calls) == 5  # one Google search per job-board site
    assert found.meta["charged_usd"] == pytest.approx(0.005)


def test_linkedin_search_params() -> None:
    cfg = RadarConfig(keywords=["GTM Engineer"], locations=["United States", "Toronto"])
    us, toronto = search_params(cfg, 86400)
    assert us == {
        "search": '"GTM Engineer"',
        "location": "United States",
        "postedLimit": "24h",
        "sortBy": "date",
        "workplaceType": "remote",  # US: remote only
    }
    assert "workplaceType" not in toronto  # Canada: on-site is fine
    assert search_params(cfg, 3 * 86400)[0]["postedLimit"] == "week"  # longer than a day: a week, then trimmed


def test_linkedin_search_reads_only_likely_postings() -> None:
    cfg = RadarConfig(keywords=["GTM Engineer"], locations=["United States", "Toronto"])
    listed = [
        linkedin_item("7", "GTM Engineer", "Zeta"),
        linkedin_item("8", "Account Executive", "Eta"),  # not a GTM title: its posting isn't read
        linkedin_item("9", "GTM Engineer", "TalentCo Staffing"),  # an agency: not read either
    ]
    treg = FakeTreg(
        {
            LINKEDIN_JOBS: pages(listed, 25),
            JOB_DETAILS: job_details(
                **{"7": {"salary": {"text": "$140K/yr - $160K/yr"}, "experienceLevel": "Mid-Senior level"}}
            ),
        }
    )
    found = search_linkedin(treg, cfg, 86400)
    assert [j["id"] for j in found.jobs] == ["li-7"]  # the same job from both searches, once
    job = found.jobs[0]
    assert job["location"] == "United States (Remote)"
    assert (job["company"], job["salary"], job["seniority"], job["apply_url"], job["applicants"]) == (
        "Zeta",
        "$140K/yr - $160K/yr",
        "Mid-Senior level",
        "https://jobs.example/7",
        "12",
    )
    assert treg.tools().count(JOB_DETAILS) == 1
    assert found.meta == {"searches": 2, "scanned": 6, "kept": 1, "spent_usd": 0.003}
    assert all(cap == pytest.approx(0.001) for *_, cap in treg.calls)  # each call capped at its list price


def test_a_full_posting_fills_in_the_job() -> None:
    listed = linkedin_item("7", "GTM Engineer", "Zeta", location="Toronto, ON")
    details = {
        "industries": [{"id": None, "name": "Software Development"}, {"name": "IT Services"}],
        "workplaceType": "hybrid",
        "location": {"linkedinText": "Toronto"},
        "salary": {"text": None, "min": 150000, "max": 170000, "currency": "CAD"},
    }
    job = parse_job(listed, details)
    assert job["industry"] == "Software Development, IT Services"
    assert job["location"] == "Toronto, ON (Hybrid)"  # the search's wording, with how it's worked
    assert job["salary"] == "CAD 150,000–170,000"
    assert parse_job(linkedin_item("8", "GTM Engineer", "Eta", location="Canada (Remote)"))["location"] == (
        "Canada (Remote)"
    )


def test_linkedin_search_keeps_the_window_and_the_cap() -> None:
    now = datetime(2026, 10, 26, 16, 0, tzinfo=UTC)
    old = (now - timedelta(days=2)).isoformat()
    listed = [linkedin_item("1", "GTM Engineer", "Recent", postedDate=(now - timedelta(hours=3)).isoformat())]
    listed += [linkedin_item("2", "GTM Engineer", "Old", postedDate=old)]
    listed += [linkedin_item(str(n), "GTM Engineer", f"Co {n}", postedDate=now.isoformat()) for n in range(10, 15)]
    cfg = RadarConfig(keywords=["GTM Engineer"], locations=["United States"], daily_usd=0.004)
    treg = FakeTreg({LINKEDIN_JOBS: pages(listed, 25), JOB_DETAILS: job_details()})
    found = search_linkedin(treg, cfg, 86400, now)
    assert "li-2" not in {j["id"] for j in found.jobs}  # older than the window
    assert treg.tools() == [LINKEDIN_JOBS] + [JOB_DETAILS] * 3  # the cap covers the search and three postings
    assert found.meta["unread"] == 3  # the rest are judged on the search result alone
    assert len(found.jobs) == 6


@pytest.mark.parametrize(("retryable", "tries"), [(False, 1), (True, 2)])
def test_a_posting_that_cant_be_read_is_judged_on_the_search_result(retryable: bool, tries: int) -> None:
    cfg = RadarConfig(keywords=["GTM Engineer"], locations=["United States"])
    listed = pages([linkedin_item("7", "GTM Engineer", "Zeta")], 25)
    treg = FakeTreg({LINKEDIN_JOBS: listed}, fail={JOB_DETAILS}, retryable=retryable)
    found = search_linkedin(treg, cfg, 86400)
    assert [j["id"] for j in found.jobs] == ["li-7"]
    assert found.meta["unread"] == 1
    assert treg.tools().count(JOB_DETAILS) == tries  # a busy treg gets one more try; a refusal doesn't


def test_a_failed_linkedin_search_raises() -> None:
    cfg = RadarConfig(keywords=["GTM Engineer"], locations=["United States"])
    with pytest.raises(RuntimeError, match="is down"):
        search_linkedin(FakeTreg(fail={LINKEDIN_JOBS}), cfg, 86400)


def test_hiring_posts() -> None:
    posts = [
        {"id": "p1", "content": "We're hiring a GTM engineer! DM me.", "author": {"name": "Pat"}},
        {"id": "p2", "content": "Open to work as a GTM engineer", "author": {"name": "Sam"}},
    ]
    treg = FakeTreg({POST_SEARCH: {"elements": posts}}, price=0.004)
    found = search_posts(treg, "24h")
    assert [p["id"] for p in found.jobs] == ["p1"]  # the same post from every query, once; no job seekers
    assert {q["postedLimit"] for _, q, _, _ in treg.calls} == {"24h"}
    assert found.meta == {"scanned": 12, "kept": 1, "window": "24h", "charged_usd": 0.024}


def test_search_window() -> None:
    assert window_seconds(None) == 86400
    assert window_seconds(0.2) == 86400  # at least a day
    assert window_seconds(30) == 7 * 86400  # at most a week
