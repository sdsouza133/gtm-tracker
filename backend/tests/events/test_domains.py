"""Which company a website or an email address belongs to."""

import pytest

from app.events.domains import registrable_domain, website


@pytest.mark.parametrize(
    ("host", "domain"),
    [
        ("acme.com", "acme.com"),
        ("www.acme.com", "acme.com"),
        ("app.eu.acme.com", "acme.com"),
        ("www.acme.co.uk", "acme.co.uk"),
        ("ACME.COM.", "acme.com"),
        ("127.0.0.1", None),
        ("localhost", None),
        ("acme", None),
    ],
)
def test_the_registrable_domain_is_the_company_part_of_a_host(host: str, domain: str | None) -> None:
    assert registrable_domain(host) == domain


@pytest.mark.parametrize(
    ("typed", "parsed"),
    [
        ("acme.com", ("https://acme.com/", "acme.com")),
        ("  https://www.acme.co.uk/about?ref=x#top ", ("https://www.acme.co.uk/about", "acme.co.uk")),
        ("https://acme.com:443/about", ("https://acme.com/about", "acme.com")),  # the standard port, said out loud
    ],
)
def test_a_website_is_read_however_it_was_typed(typed: str, parsed: tuple[str, str]) -> None:
    assert website(typed) == parsed


@pytest.mark.parametrize(
    "typed",
    [
        "",
        "acme",
        "acme .com",
        "http://127.0.0.1/",
        "http://localhost:8000",
        "ftp://acme.com",
        "https://user:secret@acme.com",
        "https://acme.com:99999",
        "http://Shop.Acme.com:8080",  # the fetcher only connects on the standard web ports
        "http://acme.com:443",
        "https://" + "a" * 2050 + ".com",
    ],
)
def test_anything_but_a_public_web_address_is_refused(typed: str) -> None:
    assert website(typed) is None
