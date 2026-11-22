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


def test_a_malformed_address_is_a_site_error_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SiteError, match="website address"):
        public_url("http://[abc")

    def bad_label(host: str, *_: Any, **__: Any) -> list[Any]:
        raise UnicodeError("label empty or too long")

    monkeypatch.setattr(socket, "getaddrinfo", bad_label)
    with pytest.raises(SiteError, match="doesn't resolve"):
        public_url("a..example")


def test_a_malformed_link_on_the_home_page_is_skipped() -> None:
    home = '<a href="http://[bad/about">Broken</a> <a href="/about">About</a>'
    pages = {"https://prospect.example": home, "https://prospect.example/about": "<p>About us</p>"}
    assert read_site("prospect.example", get=pages.__getitem__)["pages"] == list(pages)


CUSTOMER_HOME = """<html><head><title>CXHero</title></head><body>
<img src="/a.png" alt="Glowco logo"><img src="/b.png" alt=""><svg><title>skip me</title></svg>
<a href="https://www.prospect.example/customers">Customers</a> <a href="/pricing">Pricing</a>
<a href="/case-studies/mugworth">Mugworth story</a> <a href="https://elsewhere.example/customers">Elsewhere</a>
</body></html>"""
CUSTOMERS_INDEX = """<html><body><h1>Customer stories</h1>
<a href="/customers/glowco">How Glowco cut handle time in half</a>
<a href="/customers/shoebird">Shoebird automates 60%</a>
<a href="/customers">All</a> <a href="/blog/news">News</a></body></html>"""


def test_customer_pages_are_read_with_their_stories_and_logo_names() -> None:
    pages = {
        "https://prospect.example": CUSTOMER_HOME,
        "https://www.prospect.example/customers": CUSTOMERS_INDEX,
        "https://www.prospect.example/customers/glowco": "<p>Dana Named, Senior Manager CX at Glowco</p>",
        "https://www.prospect.example/customers/shoebird": "<p>Shoebird story</p>",
        "https://prospect.example/case-studies/mugworth": "<p>Mugworth story</p>",
    }
    read = site.read_customers("prospect.example", get=lambda url: pages[url])
    assert read["pages"] == [
        "https://prospect.example",
        "https://www.prospect.example/customers",  # www. or not, it's the same site
        "https://prospect.example/case-studies/mugworth",
        "https://www.prospect.example/customers/glowco",
        "https://www.prospect.example/customers/shoebird",
    ]
    text = str(read["text"])
    assert "[image] Glowco logo" in text
    assert "skip me" not in text
    assert "Dana Named, Senior Manager CX at Glowco" in text
    assert "elsewhere.example" not in " ".join(read["pages"])


def test_without_customer_links_the_usual_addresses_are_tried() -> None:
    asked: list[str] = []

    def get(url: str) -> str:
        asked.append(url)
        if url == "https://prospect.example":
            return "<html><body><a href='/pricing'>Pricing</a></body></html>"
        if url == "https://prospect.example/customers":
            raise SiteError("https://prospect.example/customers answered 404.")
        return "<p>Case studies: Glowco, Shoebird</p>"

    read = site.read_customers("https://prospect.example", get=get)
    assert asked == [
        "https://prospect.example",
        "https://prospect.example/customers",
        "https://prospect.example/case-studies",
    ]
    assert read["pages"] == ["https://prospect.example", "https://prospect.example/case-studies"]


def test_customer_pages_stop_at_the_cap() -> None:
    stories = "".join(f'<a href="/customers/brand-{n}">Brand {n}</a>' for n in range(30))
    pages = {
        "https://prospect.example": '<a href="/customers">Customers</a>',
        "https://prospect.example/customers": stories,
    }
    read = site.read_customers("prospect.example", get=lambda url: pages.get(url, "<p>story</p>"))
    assert len(read["pages"]) == site.CUSTOMER_MAX_PAGES  # type: ignore[arg-type]


def test_customer_pages_need_the_home_page() -> None:
    def down(url: str) -> str:
        raise httpx2.ConnectError("down")

    with pytest.raises(SiteError, match="Couldn't read"):
        site.read_customers("prospect.example", get=down)


def test_a_link_to_someones_linkedin_profile_is_kept_next_to_their_name() -> None:
    home = """<html><body><a href="/customers">Customers</a>
<blockquote>"It changed how we work." <a href="https://ca.linkedin.com/in/dana-named/?utm=x">Dana Named</a>, Glowco
</blockquote><a href="https://www.linkedin.com/company/glowco">Glowco on LinkedIn</a>
<a href="javascript:void(0)">Menu</a></body></html>"""
    read = site.read_customers("prospect.example", get=lambda url: home if url == "https://prospect.example" else "")
    text = str(read["text"])
    assert "[LinkedIn https://www.linkedin.com/in/dana-named] Dana Named" in text  # cleaned, and next to the name
    assert "linkedin.com/company" not in text  # a company page isn't a person
    assert "javascript" not in text
    plain = site._Text()
    plain.feed(home)
    assert not any("[LinkedIn" in part for part in plain.parts)  # only customer pages keep them


def test_failed_fetches_count_toward_a_cap_and_none_is_tried_twice() -> None:
    asked: list[str] = []
    stories = "".join(f'<a href="/customers/brand-{n}">Brand {n}</a>' for n in range(50))

    def get(url: str) -> str:
        asked.append(url)
        if url == "https://prospect.example":
            return '<a href="/customers">Customers</a>' + stories[: stories.index("brand-5")]  # links a few stories too
        if url == "https://prospect.example/customers":
            return stories
        raise httpx2.ConnectError("too slow")  # every story fails

    read = site.read_customers("prospect.example", get=get)
    assert len(asked) == site.CUSTOMER_MAX_TRIES
    assert len(asked) == len(set(asked))  # a story that failed isn't fetched again when the index links it too
    assert read["pages"] == ["https://prospect.example", "https://prospect.example/customers"]
