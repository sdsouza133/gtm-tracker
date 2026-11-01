import socket
from typing import Any

import httpx2
import pytest

from app.magnet import site
from app.magnet.site import SiteError, public_url, read_site

HOME = """<html><head><title>Prospect | Pipeline software</title>
<meta name="description" content="Pipeline software for B2B sales teams">
<script>var tracking = "do not read me";</script><style>.x{color:red}</style></head>
<body><h1>Close more deals</h1>
<a href="/about">About</a> <a href="/pricing#plans">Pricing</a> <a href="/blog/post">Blog</a>
<a href="https://elsewhere.example/about">Partner</a></body></html>"""


@pytest.fixture(autouse=True)
def dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Made-up hosts: one public, one inside a private network, one that doesn't exist."""
    ips = {"prospect.example": "93.184.216.34", "internal.example": "10.0.0.5", "localhost": "127.0.0.1"}

    def resolve(host: str, *_: Any, **__: Any) -> list[Any]:
        if host not in ips:
            raise socket.gaierror("unknown host")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ips[host], 0))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)


def test_reads_the_home_page_and_the_pages_that_say_what_they_sell() -> None:
    pages = {
        "https://prospect.example": HOME,
        "https://prospect.example/about": "<p>We help revenue teams.</p>",
        "https://prospect.example/pricing": "<p>From $99 a month.</p>",
    }
    asked: list[str] = []

    def get(url: str) -> str:
        asked.append(url)
        return pages[url]

    found = read_site("prospect.example", get=get)
    assert found["title"] == "Prospect | Pipeline software"
    assert found["pages"] == list(pages)
    assert asked == list(pages)  # not the blog, not another site
    text = str(found["text"])
    assert "Pipeline software for B2B sales teams" in text
    assert "Close more deals" in text
    assert "revenue teams" in text
    assert "do not read me" not in text
    assert "color:red" not in text


def test_a_page_that_fails_is_skipped_but_the_home_page_must_load() -> None:
    def get(url: str) -> str:
        if url.endswith("/about") or url == "https://prospect.example/pricing":
            raise SiteError("404")
        return HOME

    assert read_site("https://prospect.example", get=get)["pages"] == ["https://prospect.example"]

    def down(_: str) -> str:
        raise SiteError("503")

    with pytest.raises(SiteError, match="Couldn't read"):
        read_site("https://prospect.example", get=down)


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("ftp://prospect.example", "website address"),
        ("internal.example", "isn't a public website"),
        ("http://localhost:8000/admin", "isn't a public website"),
        ("nowhere.example", "doesn't resolve"),
    ],
)
def test_only_public_websites_are_fetched(url: str, message: str) -> None:
    with pytest.raises(SiteError, match=message):
        public_url(url)


def test_a_bare_domain_gets_https() -> None:
    assert public_url("prospect.example") == "https://prospect.example"


def test_fetching_follows_redirects_only_to_public_hosts_and_reads_web_pages_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def server(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/moved":
            return httpx2.Response(302, headers={"location": "/home"})
        if request.url.path == "/sneaky":
            return httpx2.Response(302, headers={"location": "http://internal.example/admin"})
        if request.url.path == "/file.pdf":
            return httpx2.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF")
        if request.url.path == "/missing":
            return httpx2.Response(404)
        return httpx2.Response(200, headers={"content-type": "text/html"}, content=b"<p>hi</p>" + b"x" * site.MAX_BYTES)

    real = httpx2.Client
    monkeypatch.setattr(httpx2, "Client", lambda **kw: real(transport=httpx2.MockTransport(server), **kw))
    page = site._get("https://prospect.example/moved")
    assert page.startswith("<p>hi</p>")
    assert len(page) == site.MAX_BYTES
    for path, message in [
        ("/sneaky", "isn't a public website"),
        ("/file.pdf", "isn't a web page"),
        ("/missing", "404"),
    ]:
        with pytest.raises(SiteError, match=message):
            site._get(f"https://prospect.example{path}")
