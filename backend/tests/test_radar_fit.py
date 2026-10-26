"""Which roles fit: titles, places and pay."""

import pytest

from app.radar.fit import (
    RadarConfig,
    core_role,
    fits,
    flags_for,
    pay_ok,
    title_score,
    web_url,
    workable_from_toronto,
)

CFG = RadarConfig()


@pytest.mark.parametrize(
    ("title", "score"),
    [
        ("GTM Engineer", 3),
        ("Senior Go-To-Market Engineer", 3),
        ("Revenue Operations Manager", 2),
        ("Salesforce Administrator", 1),
        ("GTM Recruiter", 0),
        ("Account Executive", 0),
    ],
)
def test_title_score(title: str, score: int) -> None:
    assert title_score(title) == score


def test_core_roles() -> None:
    assert core_role("Founding GTM Engineer")
    assert not core_role("GTM Systems Analyst")
    assert not core_role("RevOps Manager")


@pytest.mark.parametrize(
    ("location", "text", "ok"),
    [
        ("Remote", "", True),
        ("Remote - US", "", False),  # US-only remote: needs US residency
        ("Remote - US or Canada", "", True),
        ("Toronto, ON", "", True),
        ("New York, NY (On-site)", "", False),
        ("United States", "", True),
        ("Remote", "You must be authorized to work in the United States without sponsorship", False),
        ("Remote (Hybrid)", "", False),
    ],
)
def test_workable_from_toronto(location: str, text: str, ok: bool) -> None:
    assert workable_from_toronto(location, text) is ok


@pytest.mark.parametrize(
    ("salary", "canadian", "ok"),
    [
        ("$90K-$120K", False, True),
        ("$70,000 - $95,000", False, False),
        ("CA$110,000-130,000", False, False),
        ("$140,000 - $150,000", True, True),  # a plain "$" in Canada is CAD: 150K CAD clears the CAD floor
        ("$120,000 - $130,000", True, False),
        ("$60/hr", False, True),
        ("", False, True),
        ("Competitive", False, True),
    ],
)
def test_pay_floor(salary: str, canadian: bool, ok: bool) -> None:
    assert pay_ok(salary, CFG, canadian) is ok


def test_fits_explains_why_not() -> None:
    assert fits({"title": "GTM Engineer", "location": "Remote", "salary": "$150K-$180K"}, CFG) == (True, "")
    assert fits({"title": "RevOps Analyst", "location": "Remote"}, CFG)[1] == "not a GTM engineering role"
    assert fits({"title": "GTM Engineer", "location": "Austin, TX"}, CFG)[1] == "on-site in the US, or US-only"
    us_only = {"title": "GTM Engineer", "location": "Remote", "flags": ["us_only"]}
    assert fits(us_only, CFG)[1] == "on-site in the US, or US-only"
    assert fits({"title": "GTM Engineer", "location": "Remote", "salary": "$60K-$80K"}, CFG)[1] == "pay under the floor"
    loose = RadarConfig(core_only=False, toronto_ok=False)
    assert fits({"title": "RevOps Analyst", "location": "Austin, TX"}, loose) == (True, "")


def test_config_from_setting_ignores_unknown_and_empty_values() -> None:
    cfg = RadarConfig.from_setting({"hour": 9, "keywords": [], "nonsense": 1})
    assert (cfg.hour, cfg.keywords[0]) == (9, "GTM Engineer")
    assert RadarConfig.from_setting(None) == RadarConfig()


def test_flags() -> None:
    assert flags_for("Toronto, ON", "") == ["canada"]
    assert flags_for("New York", "We're a remote-first team. Must be a US citizen.") == ["remote", "us_only"]


def test_web_url_keeps_only_http_links() -> None:
    assert web_url(" https://jobs.example/1 ") == "https://jobs.example/1"
    assert web_url("HTTP://jobs.example") == "HTTP://jobs.example"
    assert web_url("javascript:alert(1)") == ""
    assert web_url(None) == ""
