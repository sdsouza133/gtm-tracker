"""Read a prospect's website for free: the home page and a few pages that say what they sell and to whom, or (for
a champion report) the pages where it shows its customers.

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
# where a company shows who uses it: customer and case-study pages, success stories, testimonials, a wall of love
CUSTOMER_PAGES = re.compile(
    r"/(customers?|customer-stor\w*|case-stud\w*|success-stor\w*|testimonials?|clients?|wall-of-love)(/|$)", re.I
)
CUSTOMER_GUESSES = ("/customers", "/case-studies")  # tried when the home page links to neither
CUSTOMER_MAX_PAGES = 10
CUSTOMER_MAX_TRIES = 20  # fetches in all, failed ones too: a site that times out can't hold a build up for long
CUSTOMER_MAX_CHARS = 48_000
INDEX_CHARS = 16_000  # a customers page can list dozens of stories
STORY_CHARS = 4_000
# a person's LinkedIn profile, as a quote or a case study links their name to it
LINKEDIN_PROFILE = re.compile(r"^https?://(?:[a-z]{2,3}\.)?(?:www\.)?linkedin\.com/in/([\w%.-]+)/?(?:[?#].*)?$", re.I)


class SiteError(RuntimeError):
    pass


class _Text(HTMLParser):
    def __init__(self, *, alts: bool = False) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.links: list[str] = []
        self.title = ""
        self.alts = alts  # keep images' alt text: a logo wall names its customers only there
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIP_TAGS:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "img" and self.alts and not self._skip:
            alt = (dict(attrs).get("alt") or "").strip()
            if alt:
                self.parts.append(f"[image] {alt}")
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
                profile = linkedin_profile(href) if self.alts and not self._skip else ""
                if profile:  # kept where the link is, so it sits next to the name it's on
                    self.parts.append(f"[LinkedIn {profile}]")
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


def linkedin_profile(href: str) -> str:
    """The LinkedIn profile a link points to, without its tracking (query or fragment), or "" for any other link."""
    m = LINKEDIN_PROFILE.match(href.strip())
    return f"https://www.linkedin.com/in/{m.group(1)}" if m else ""


def public_url(url: str) -> str:
    """The URL with a scheme, if it points at a public host; SiteError otherwise."""
    if "://" not in url:
        url = "https://" + url
    try:
        parsed = urlparse(url)
        host = parsed.hostname
    except ValueError as e:  # "http://[abc", say
        raise SiteError("Give a website address, like acme.com.") from e
    if parsed.scheme not in ("http", "https") or not host:
        raise SiteError("Give a website address, like acme.com.")
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError) as e:  # UnicodeError: an empty or over-long label, like "a..com"
        raise SiteError(f"{host} doesn't resolve.") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise SiteError(f"{host} isn't a public website.")
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
        except (httpx2.HTTPError, httpx2.InvalidURL, SiteError):
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
                try:  # the page is someone else's: a malformed link is skipped, not fatal
                    link = urljoin(home, href).split("#")[0]
                    target = urlparse(link)
                    same_host = target.hostname == host
                except ValueError:
                    continue
                if same_host and USEFUL.search(target.path) and link not in queue:
                    queue.append(link)
    return {"url": home, "title": title, "pages": pages, "text": "\n\n".join(texts)[:MAX_CHARS]}


def read_customers(url: str, get: Callable[[str], str] | None = None) -> dict[str, object]:
    """The pages where a company shows its customers: the home page (logo walls, quotes), then its customer,
    case-study and testimonial pages and the stories one level under them, at most CUSTOMER_MAX_PAGES read and
    CUSTOMER_MAX_TRIES fetched. Images count by their alt text, and a link to someone's LinkedIn profile by its
    address. When the home page links to none of them, the usual addresses are tried. Same shape as `read_site`;
    `get` returns a page's HTML."""
    fetch = get or _get
    home = public_url(url)
    origin = "{0.scheme}://{0.netloc}".format(urlparse(home))
    host = _bare(urlparse(home).hostname)
    pages: list[str] = []
    texts: list[str] = []

    def read(page: str, limit: int) -> _Text | None:
        try:
            html = fetch(page)
        except (httpx2.HTTPError, httpx2.InvalidURL, SiteError):
            return None
        parser = _Text(alts=True)
        parser.feed(html)
        pages.append(page)
        texts.append(f"[{page}]\n" + " ".join(parser.parts)[:limit])
        return parser

    first = read(home, PAGE_CHARS)
    if first is None:
        raise SiteError(f"Couldn't read {home}.")
    queue = sorted(
        (link for link in _links(home, first.links, host) if CUSTOMER_PAGES.search(urlparse(link).path)),
        key=lambda link: urlparse(link).path.rstrip("/").count("/"),  # the customers page before its stories
    ) or [origin + path for path in CUSTOMER_GUESSES]
    tried = {home}
    while queue and len(pages) < CUSTOMER_MAX_PAGES and len(tried) < CUSTOMER_MAX_TRIES:
        page = queue.pop(0)
        if page in tried:  # read, or failed: either way not fetched again when another page links to it
            continue
        tried.add(page)
        index = urlparse(page).path.rstrip("/").count("/") <= 1
        parsed = read(page, INDEX_CHARS if index else STORY_CHARS)
        if parsed is None or not index:
            continue
        under = urlparse(page).path.rstrip("/") + "/"
        queue += [link for link in _links(page, parsed.links, host) if urlparse(link).path.startswith(under)]
    return {"url": home, "title": first.title.strip(), "pages": pages, "text": "\n\n".join(texts)[:CUSTOMER_MAX_CHARS]}


def _bare(host: str | None) -> str:
    return (host or "").lower().removeprefix("www.")


def _links(base: str, hrefs: list[str], host: str) -> list[str]:
    """The page's links on the same site (www. or not), without fragments, each once."""
    out: list[str] = []
    for href in hrefs:
        try:  # the page is someone else's: a malformed link is skipped, not fatal
            link = urljoin(base, href).split("#")[0]
            target = urlparse(link)
        except ValueError:
            continue
        if target.scheme in ("http", "https") and _bare(target.hostname) == host and link not in out:
            out.append(link)
    return out


def _get(url: str) -> str:
    """One page's HTML. Every hop of a redirect is checked, so a public page can't bounce the fetch to a private
    host, and only the first MAX_BYTES are read, so a huge file can't fill memory."""
    with httpx2.Client(timeout=TIMEOUT_S, follow_redirects=False, headers={"User-Agent": USER_AGENT}) as client:
        for _ in range(MAX_REDIRECTS + 1):
            public_url(url)
            with client.stream("GET", url) as r:
                if r.status_code in REDIRECTS and "location" in r.headers:
                    try:
                        url = urljoin(url, r.headers["location"])
                    except ValueError as e:
                        raise SiteError(f"{url} redirects somewhere that isn't a web address.") from e
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
