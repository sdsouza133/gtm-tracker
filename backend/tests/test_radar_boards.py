"""Finding and reading a company's job board, with a fake network."""

import socket
from datetime import date

import httpx2
import pytest

from app.radar import boards
from tests.radar_fakes import FakeWeb, ashby, ashby_job

UUID1 = "11111111-1111-1111-1111-111111111111"
UUID2 = "22222222-2222-2222-2222-222222222222"


def test_a_board_linked_from_the_careers_page_is_trusted() -> None:
    web = FakeWeb(
        json_by_url=ashby("acme", ashby_job("GTM Engineer", UUID1), ashby_job("Account Executive", UUID2)),
        text_by_url={"https://acme.example/careers": '<a href="https://jobs.ashbyhq.com/acme">Jobs</a>'},
    )
    res = boards.find_jobs(web, "Acme", "acme.example")
    assert res.board is not None
    assert (res.board["ats"], res.board["found_via"], res.board["open_roles"]) == ("ashby", "careers page", 2)
    assert [p["title"] for p in res.postings] == ["GTM Engineer"]  # GTM roles only


def test_a_guessed_board_needs_proof_it_is_theirs() -> None:
    other = ashby_job("GTM Engineer", UUID1, descriptionPlain="Join another.example")
    assert boards.find_jobs(FakeWeb(json_by_url=ashby("acme", other)), "Acme", "acme.example").board is None
    mine = ashby_job("GTM Engineer", UUID1)  # mentions acme.example
    found = boards.find_jobs(FakeWeb(json_by_url=ashby("acme", mine)), "Acme", "acme.example")
    assert found.board is not None
    assert found.board["found_via"] == "domain"


def test_a_known_board_with_no_openings_is_still_theirs() -> None:
    known = {"ats": "ashby", "slug": "acme", "found_via": "careers page"}
    res = boards.find_jobs(FakeWeb(json_by_url=ashby("acme")), "Acme", "acme.example", board=known)
    assert res.board is not None
    assert res.postings == []
    assert "none GTM-related" in res.note


def test_jobs_record_keeps_seen_urls_newest_first_and_marks_new_postings() -> None:
    res = boards.BoardResult(
        board={"ats": "ashby", "slug": "acme"},
        postings=[{"title": "GTM Engineer", "url": "u2", "fit": 3}, {"title": "GTM Ops", "url": "u1", "fit": 2}],
        note="",
    )
    jobs = res.as_jobs(["u1", "old"], {"u1": "2026-10-01"}, date(2026, 10, 26))
    assert jobs["seen"] == ["u2", "u1", "old"]
    assert [p["first_seen"] for p in jobs["postings"]] == ["2026-10-26", "2026-10-01"]


def test_readers_parse_each_board() -> None:
    web = FakeWeb(
        json_by_url={
            "https://boards-api.greenhouse.io/v1/boards/acme": {"name": "Acme"},
            "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true": {
                "jobs": [
                    {
                        "title": "GTM Engineer",
                        "absolute_url": "g1",
                        "location": {"name": "Toronto"},
                        "first_published": "2026-10-20T00:00",
                    }
                ]
            },
            "https://api.lever.co/v0/postings/acme?mode=json": [
                {
                    "text": "GTM Engineer",
                    "hostedUrl": "l1",
                    "categories": {"location": "Remote"},
                    "createdAt": 1793000000000,
                }
            ],
            "https://apply.workable.com/api/v1/widget/accounts/acme": {
                "name": "Acme",
                "jobs": [
                    {
                        "title": "GTM Engineer",
                        "url": "w1",
                        "city": "Austin",
                        "country": "US",
                        "published_on": "2026-10-21",
                    }
                ],
            },
            "https://api.smartrecruiters.com/v1/companies/acme/postings?limit=100&offset=0": {
                "totalFound": 1,
                "content": [
                    {"name": "GTM Engineer", "id": "9", "company": {"name": "Acme"}, "location": {"city": "Toronto"}}
                ],
            },
        }
    )
    assert boards.read(web, "greenhouse", "acme") == (
        "Acme",
        [{"title": "GTM Engineer", "url": "g1", "location": "Toronto", "posted": "2026-10-20", "text": ""}],
    )
    lever = boards.read(web, "lever", "acme")
    assert lever is not None
    assert lever[1][0]["posted"] == "2026-10-26"
    workable = boards.read(web, "workable", "acme")
    assert workable is not None
    assert workable[1][0]["location"] == "Austin, US"
    smart = boards.read(web, "smartrecruiters", "acme")
    assert smart is not None
    assert smart[1][0]["url"] == "https://jobs.smartrecruiters.com/acme/9"
    assert boards.read(web, "lever", "missing") is None


def test_slug_guesses() -> None:
    guesses = boards.slug_guesses("Acme Labs Inc", "getacme.io")
    assert guesses[:3] == ["acme", "getacme", "acmelabsinc"]
    assert "acmehq" in guesses


def test_the_real_network_reaches_only_public_addresses() -> None:
    sent: list[httpx2.Request] = []

    def site(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        if request.url.path == "/careers":  # a public page that redirects inward
            return httpx2.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data/"})
        if request.url.path == "/moved":
            return httpx2.Response(302, headers={"Location": "/jobs"})
        return httpx2.Response(200, text="ok")

    web = boards.Web(inner=httpx2.MockTransport(site))
    assert web.text("https://93.184.216.34/moved") == "ok"  # a relative redirect keeps the site's name
    assert [r.url.path for r in sent] == ["/moved", "/jobs"]
    for url in ("https://93.184.216.34/careers", "http://127.0.0.1/", "http://10.0.0.5/", "http://localhost/"):
        with pytest.raises(boards.BlockedURLError):
            web.text(url)
    assert boards.boards_on_careers_page(web, "127.0.0.1") == []  # a crafted domain finds nothing, quietly


def test_requests_go_to_the_address_that_was_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["93.184.216.34", "127.0.0.1"])  # a DNS answer that changes after the check

    def resolve(host: str, port: int, **_: object) -> list[tuple[object, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (next(answers), port))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    sent: list[httpx2.Request] = []

    def site(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200, text="ok")

    web = boards.Web(inner=httpx2.MockTransport(site))
    assert web.text("https://jobs.acme.example/careers") == "ok"
    (r,) = sent
    assert (r.url.host, r.headers["Host"], r.extensions["sni_hostname"]) == (
        "93.184.216.34",
        "jobs.acme.example",
        "jobs.acme.example",
    )


def test_a_board_belongs_by_domain_not_by_a_longer_one() -> None:
    post = [{"title": "GTM Engineer", "url": "https://jobs.example/1", "text": "Apply at notacme.example"}]
    assert boards.belongs("Acme", "acme.example", "Other", post) == ""
    post[0]["text"] = "Apply at careers.acme.example today."
    assert boards.belongs("Acme", "acme.example", "Other", post) == "domain"
    post[0]["text"] = "See acme.example.evil for more"
    assert boards.belongs("Acme", "acme.example", "Other", post) == ""


def test_a_relative_redirect_keeps_the_site_name(monkeypatch: pytest.MonkeyPatch) -> None:
    def resolve(host: str, port: int, **_: object) -> list[tuple[object, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    sent: list[httpx2.Request] = []

    def site(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        if request.url.path == "/moved":
            return httpx2.Response(302, headers={"Location": "/jobs"})
        return httpx2.Response(200, text="ok")

    web = boards.Web(inner=httpx2.MockTransport(site))
    assert web.text("https://jobs.acme.example/moved") == "ok"
    assert [(r.url.host, r.url.path, r.headers["Host"], r.extensions["sni_hostname"]) for r in sent] == [
        ("93.184.216.34", "/moved", "jobs.acme.example", "jobs.acme.example"),
        ("93.184.216.34", "/jobs", "jobs.acme.example", "jobs.acme.example"),
    ]
