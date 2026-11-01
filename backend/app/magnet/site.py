"""Read a prospect's website for free: the home page and a few pages that say what they sell and to whom.

Only public http(s) addresses are fetched; anything that resolves to a private, loopback or link-local address is
refused, so a typed URL can't reach inside the network the tracker runs on.
"""

import ipaddress
import re
import socket
from collections.abc import Callable
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx2

MAX_PAGES = 5
MAX_CHARS = 24_000  # all pages together; plenty for an ICP, cheap to send
PAGE_CHARS = 8_000
TIMEOUT_S = 15
MAX_BYTES = 2_000_000
MAX_REDIRECTS = 3
REDIRECTS = frozenset({301, 302, 303, 307, 308})
USER_AGENT = "Mozilla/5.0 (compatible; gtm-tracker)"
USEFUL = re.compile(
    r"/(about|company|product|platform|solutions?|pricing|customers?|case-stud|use-cases?|industries)", re.I
)
SKIP_TAGS = {"script", "style", "noscript", "svg", "template", "iframe"}


class SiteError(RuntimeError):
    pass


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.links: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIP_TAGS:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
        if tag == "meta":
            a = dict(attrs)
            if (a.get("name") or a.get("property") or "").lower() in ("description", "og:description") and a.get(
                "content"
            ):
                self.parts.append(str(a["content"]))

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip and data.strip():
            self.parts.append(data.strip())


def public_url(url: str) -> str:
    """The URL with a scheme, if it points at a public host; SiteError otherwise."""
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise SiteError("Give a website address, like acme.com.")
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as e:
        raise SiteError(f"{parsed.hostname} doesn't resolve.") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise SiteError(f"{parsed.hostname} isn't a public website.")
    return url


def read_site(url: str, get: Callable[[str], str] | None = None) -> dict[str, object]:
    """The site's title, its text (home page first) and the pages read. `get` returns a page's HTML."""
    fetch = get or _get
    home = public_url(url)
    pages: list[str] = []
    texts: list[str] = []
    title = ""
    queue = [home]
    host = urlparse(home).hostname
    while queue and len(pages) < MAX_PAGES:
        page = queue.pop(0)
        if page in pages:
            continue
        try:
            html = fetch(page)
        except (httpx2.HTTPError, SiteError):
            if page == home:
                raise SiteError(f"Couldn't read {home}.") from None
            continue
        parser = _Text()
        parser.feed(html)
        pages.append(page)
        title = title or parser.title.strip()
        texts.append(f"[{page}]\n" + " ".join(parser.parts)[:PAGE_CHARS])
        if page == home:
            for href in parser.links:
                link = urljoin(home, href).split("#")[0]
                if urlparse(link).hostname == host and USEFUL.search(urlparse(link).path) and link not in queue:
                    queue.append(link)
    return {"url": home, "title": title, "pages": pages, "text": "\n\n".join(texts)[:MAX_CHARS]}


def _get(url: str) -> str:
    """One page's HTML. Every hop of a redirect is checked, so a public page can't bounce the fetch to a private
    host, and only the first MAX_BYTES are read, so a huge file can't fill memory."""
    with httpx2.Client(timeout=TIMEOUT_S, follow_redirects=False, headers={"User-Agent": USER_AGENT}) as client:
        for _ in range(MAX_REDIRECTS + 1):
            public_url(url)
            with client.stream("GET", url) as r:
                if r.status_code in REDIRECTS and "location" in r.headers:
                    url = urljoin(url, r.headers["location"])
                    continue
                if r.status_code >= 400:  # noqa: PLR2004
                    raise SiteError(f"{url} answered {r.status_code}.")
                if "html" not in r.headers.get("content-type", "text/html"):
                    raise SiteError(f"{url} isn't a web page.")
                body = bytearray()
                for chunk in r.iter_bytes():
                    body += chunk
                    if len(body) >= MAX_BYTES:
                        break
                return bytes(body[:MAX_BYTES]).decode(r.encoding or "utf-8", errors="replace")
    raise SiteError(f"{url} redirects too many times.")
