"""The paid searches, with Apify faked."""

from datetime import date

from app.radar.fit import RadarConfig
from app.radar.sources import GOOGLE_SEARCH, LINKEDIN_JOBS, search_ats, search_linkedin, search_urls, window_seconds
from tests.radar_fakes import FakeApify, FakeWeb, ashby, ashby_job, linkedin_item

UUID_FIT = "dddddddd-dddd-dddd-dddd-dddddddddddd"
UUID_OLD = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"


def test_job_boards_found_through_google_are_read_from_the_board() -> None:
    pages = [
        {
            "organicResults": [
                {"url": f"https://jobs.ashbyhq.com/acme/{UUID_FIT}"},
                {"url": "https://example.com/nothing"},
            ]
        },
        {"organicResults": [{"url": f"https://jobs.ashbyhq.com/acme/{UUID_OLD}"}]},
    ]
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
    found = search_ats(FakeApify({GOOGLE_SEARCH: pages}), web, RadarConfig(), days=2, today=date(2026, 10, 26))
    assert [j["job_id"] for j in found.jobs] == [UUID_FIT]  # only searched postings, only recent ones
    job = found.jobs[0]
    assert (job["company"], job["source"], job["board"], job["salary"]) == (
        "Acme",
        "ashby board",
        {"ats": "ashby", "slug": "acme"},
        "$150K – $170K",
    )
    assert (found.meta["boards"], found.meta["read"], found.meta["kept"]) == (1, 2, 1)


def test_linkedin_search() -> None:
    cfg = RadarConfig(keywords=["GTM Engineer"], locations=["United States", "Toronto"])
    urls = search_urls(cfg, 86400)
    assert len(urls) == 2
    assert "f_WT=2" in urls[0]  # US: remote only
    assert "f_WT" not in urls[1]  # Canada: on-site is fine
    apify = FakeApify(
        {LINKEDIN_JOBS: [linkedin_item("7", "GTM Engineer", "Zeta"), linkedin_item("7", "GTM Engineer", "Zeta")]}
    )
    found = search_linkedin(apify, cfg, 86400)
    assert [j["id"] for j in found.jobs] == ["li-7"]  # de-duplicated
    assert found.meta == {"searches": 2, "scanned": 2, "kept": 1, "spent_usd": 0.0}


def test_search_window() -> None:
    assert window_seconds(None) == 86400
    assert window_seconds(0.2) == 86400  # at least a day
    assert window_seconds(30) == 7 * 86400  # at most a week
