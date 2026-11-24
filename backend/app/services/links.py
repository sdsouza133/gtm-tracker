"""LinkedIn profile links from Apollo for people the tracker only has a name for, on the board and the Fractional list.

Only the link is kept, never an email or anything else Apollo sends back. A link is kept only when Apollo's person has
the same first name and last name as ours and works at the same company. Apollo's own confidence isn't trusted: it has
called a stranger with another last name a sure match, and the right person an unsure one. Everyone asked about is
marked tried, so a miss is never paid for twice, and each batch of ten is saved as it goes.
"""

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol
from urllib.parse import urlparse

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session, contains_eager

from app.enrich.apollo import BULK, ApolloError
from app.models import Company, Person, Prospect
from app.services.history import record

PROFILE = re.compile(r"linkedin\.com/in/([^/?#\s]+)", re.IGNORECASE)
ASIDE = re.compile(r"\([^)]*\)")  # "(Will)" in "William (Will) Cielen", "(MISUMI Americas)" after a company's name
CLOSED = {"lost", "skipped"}  # Fractional prospects not worth a credit
PAGE = 200  # rows read at a time while looking for people to ask about, so a big table is never loaded whole


class LinkFinder(Protocol):
    def bulk_match(self, details: list[dict[str, Any]]) -> list[dict[str, Any] | None]: ...


@dataclass(frozen=True)
class Filled:
    tried: int = 0  # people Apollo was asked about this time
    found: int = 0  # of them, how many now have a link
    left: int = 0  # people still to ask about, past this run's limit

    def __add__(self, other: "Filled") -> "Filled":
        return Filled(self.tried + other.tried, self.found + other.found, self.left + other.left)


def tokens(text: str) -> list[str]:
    """Lowercase words without accents or punctuation: "Sébastien O'Neil" is sebastien, o, neil."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return [t for t in re.split(r"[^a-z]+", plain) if t]


def plain_name(name: str) -> str:
    """The name without the asides in brackets: what Apollo is asked about."""
    return " ".join(ASIDE.sub(" ", name).split())


def askable(name: str) -> bool:
    """A first name and a last name of more than an initial: one word could be anyone, and "Zac C." can't be
    checked."""
    core = tokens(plain_name(name))
    return len(core) >= 2 and any(len(t) > 1 for t in core[1:])  # noqa: PLR2004


def host(value: str) -> str:
    v = value.strip().lower()
    if not v:
        return ""
    found = urlparse(v if "://" in v else f"http://{v}").hostname or ""
    return found.removeprefix("www.")


def same_domain(a: str, b: str) -> bool:
    """The same site, or one a part of the other (eu.acme.example and acme.example)."""
    a, b = host(a), host(b)
    return bool(a and b) and (a == b or a.endswith(f".{b}") or b.endswith(f".{a}"))


def profile_link(url: object) -> str | None:
    """A LinkedIn profile, as https://www.linkedin.com/in/<handle>; anything else is None."""
    m = PROFILE.search(url) if isinstance(url, str) else None
    return f"https://www.linkedin.com/in/{m.group(1)}" if m else None


def _same_name(name: str, hit: dict[str, Any]) -> bool:
    core = tokens(plain_name(name))
    every = {core[0]} | (set(tokens(name)) - set(core))  # the first name and nicknames: "William (Will) Cielen"
    first, last = core[0], {t for t in core[1:] if len(t) > 1}
    hit_first = tokens(str(hit.get("first_name") or ""))
    hit_last = [t for t in tokens(str(hit.get("last_name") or "")) if len(t) > 1]
    if not hit_first or not hit_last:
        return False
    f = hit_first[0]
    short = min(len(f), len(first)) >= 3  # noqa: PLR2004 (Dan for Daniel, not D for anyone)
    first_ok = f in every or (short and (f.startswith(first) or first.startswith(f)))
    return first_ok and any(t in last for t in hit_last)


def _same_company(company: str, domain: str | None, hit: dict[str, Any]) -> bool:
    raw = hit.get("organization")
    org: dict[str, Any] = raw if isinstance(raw, dict) else {}
    org_domain = host(str(org.get("primary_domain") or "")) or host(str(org.get("website_url") or ""))
    if org_domain:
        return bool(domain) and same_domain(org_domain, domain or "")
    # Apollo has no domain for the employer: its name must carry ours ("Phreesia Network Solutions" for Phreesia)
    ours, theirs = tokens(plain_name(company)), set(tokens(str(org.get("name") or "")))
    return bool(ours) and all(t in theirs for t in ours)


def verified_link(name: str, company: str, domain: str | None, hit: dict[str, Any] | None) -> str | None:
    """Apollo's profile link for this person, only when the first name, the last name and the company all agree."""
    if not hit or not askable(name):
        return None
    link = profile_link(hit.get("linkedin_url"))
    if link is None or not _same_name(name, hit) or not _same_company(company, domain, hit):
        return None
    return link


def _ask(name: str, company: str, domain: str | None, email: str | None = None) -> dict[str, Any]:
    ask: dict[str, Any] = {"name": plain_name(name), "organization_name": plain_name(company)}
    if domain:
        ask["domain"] = domain
    if email:
        ask["email"] = email  # a work email we already have pins the person down best
    return ask


def _chunks[T](items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _people(n: int) -> str:
    return "1 person" if n == 1 else f"{n} people"


def _pages[T](session: Session, query: Select[T]) -> Iterator[Sequence[T]]:
    """The query's rows a page at a time. Its order must be stable, so it ends with the primary key."""
    offset = 0
    while rows := session.scalars(query.limit(PAGE).offset(offset)).all():
        yield rows
        offset += PAGE


def _keep[T](items: Iterable[T], limit: int) -> tuple[list[T], int]:
    """The first `limit` items, and how many more there were: counted, not kept."""
    kept: list[T] = []
    more = 0
    for item in items:
        if len(kept) < limit:
            kept.append(item)
        else:
            more += 1
    return kept, more


# ----------------------------------------------------------------------------- the board


def board_to_ask(person: Person) -> bool:
    """Still at the company, no link, never asked about, and findable: a full name and the company's domain."""
    return (
        not person.left
        and not (person.linkedin or "").strip()
        and not person.details.get("link_tried")
        and bool(person.company.domain)
        and askable(person.name)
    )


def _board_todo(session: Session) -> Iterator[Person]:
    query = (
        select(Person)
        .join(Person.company)
        .where(
            Person.left.is_(False),
            or_(Person.linkedin.is_(None), Person.linkedin == ""),
            Company.domain.is_not(None),
            Company.domain != "",
        )
        .options(contains_eager(Person.company))
        .order_by(Person.created_at, Person.id)
    )
    for page in _pages(session, query):
        yield from (p for p in page if board_to_ask(p))


def fill_board(session: Session, apollo: LinkFinder, today: date, limit: int) -> Filled:
    """Links for people on the board, oldest first, up to `limit` people."""
    todo, more = _keep(_board_todo(session), max(limit, 0))
    tried = found = 0
    for chunk in _chunks(todo, BULK):
        try:
            hits = apollo.bulk_match([_ask(p.name, p.company.name, p.company.domain, p.email) for p in chunk])
        except ApolloError:
            break  # Apollo is down or out of credits: the rest are asked about next time
        at: Counter[tuple[str, str]] = Counter()
        for person, hit in zip(chunk, hits, strict=True):
            link = verified_link(person.name, person.company.name, person.company.domain, hit)
            session.refresh(person, ["linkedin", "details"], with_for_update=True)  # a link typed in meanwhile wins
            details = {**person.details, "link_tried": today.isoformat()}
            if link and not (person.linkedin or "").strip():
                person.linkedin = link
                details["link_source"] = "apollo"
                at[person.company_id, person.company.name] += 1
            person.details = details
        for (company_id, name), n in at.items():
            record(session, "research", f"{name}: Apollo found LinkedIn for {_people(n)}", company_id=company_id)
        tried, found = tried + len(chunk), found + sum(at.values())
        session.commit()
    return Filled(tried=tried, found=found, left=more + len(todo) - tried)


# ----------------------------------------------------------------------------- the Fractional list


def _fractional_todo(session: Session) -> Iterator[tuple[Prospect, dict[str, Any]]]:
    """Each research person with no link yet, newest prospects first. Links found live in the prospect's `mine`, which
    the daily research sync never touches, so they outlast it."""
    query = (
        select(Prospect).where(Prospect.domain.is_not(None)).order_by(Prospect.day.desc(), Prospect.rank, Prospect.id)
    )
    for page in _pages(session, query):
        for p in page:
            mine = p.mine or {}
            if (mine.get("status") or "open") in CLOSED:
                continue
            done = {**(mine.get("links") or {}), **(mine.get("links_tried") or {})}
            for person in (p.research or {}).get("people") or []:
                key, name = str(person.get("key") or ""), str(person.get("name") or "")
                if key and not person.get("linkedin") and key not in done and askable(name):
                    yield p, person


def fill_fractional(session: Session, apollo: LinkFinder, today: date, limit: int) -> Filled:
    """Links for people on the Fractional list, up to `limit` people."""
    todo, more = _keep(_fractional_todo(session), max(limit, 0))
    tried = found = 0
    for chunk in _chunks(todo, BULK):
        try:
            hits = apollo.bulk_match([_ask(str(x["name"]), p.name, p.domain) for p, x in chunk])
        except ApolloError:
            break
        results: dict[str, list[tuple[str, str | None]]] = {}
        prospects: dict[str, Prospect] = {}
        for (p, x), hit in zip(chunk, hits, strict=True):
            results.setdefault(p.id, []).append((str(x["key"]), verified_link(str(x["name"]), p.name, p.domain, hit)))
            prospects[p.id] = p
        for pid, pairs in results.items():
            p = prospects[pid]
            session.refresh(p, ["mine"], with_for_update=True)  # a tick saved during the lookup stays
            mine = dict(p.mine or {})
            links, asked = dict(mine.get("links") or {}), dict(mine.get("links_tried") or {})
            new = 0
            for key, link in pairs:
                asked[key] = today.isoformat()
                if link and key not in links:
                    links[key] = link
                    new += 1
            p.mine = {**mine, "links": links, "links_tried": asked}
            if new:
                record(session, "fractional", f"{p.name}: Apollo found LinkedIn for {_people(new)}")
            found += new
        tried += len(chunk)
        session.commit()
    return Filled(tried=tried, found=found, left=more + len(todo) - tried)


def fill(session: Session, apollo: LinkFinder, today: date, limit: int) -> Filled:
    """The board first (the people you're writing to now), then the Fractional list, up to `limit` people in all."""
    board = fill_board(session, apollo, today, limit)
    return board + fill_fractional(session, apollo, today, limit - board.tried)
