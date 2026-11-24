"""LinkedIn profile links and verified work emails from Apollo, for people on the board and the Fractional list.

One Apollo match per person brings both. A match is used only when Apollo's person has the same first name and last
name as ours and works at the same company: Apollo's own confidence isn't trusted, because it has called a stranger with
another last name a sure match, and the right person an unsure one. An email is kept only when Apollo has verified it
and it's at the company's domain. Nothing else Apollo sends back is kept. Everyone asked about is marked tried, so
nobody is paid for twice, and each batch of ten is saved as it goes.
"""

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol
from urllib.parse import urlparse

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, contains_eager

from app.enrich.apollo import BULK, ApolloError, verified_email
from app.models import Company, Person, Prospect
from app.services.history import record

PROFILE = re.compile(r"linkedin\.com/in/([^/?#\s]+)", re.IGNORECASE)
ASIDE = re.compile(r"\([^)]*\)")  # "(Will)" in "William (Will) Cielen", "(MISUMI Americas)" after a company's name
CLOSED = {"lost", "skipped"}  # Fractional prospects not worth a credit
PAGE = 200  # rows read at a time while looking for people to ask about, so a big table is never loaded whole


class ContactFinder(Protocol):
    def bulk_match(self, details: list[dict[str, Any]]) -> list[dict[str, Any] | None]: ...


@dataclass(frozen=True)
class Contact:
    link: str | None = None
    email: str | None = None


@dataclass(frozen=True)
class Filled:
    tried: int = 0  # people Apollo was asked about this time
    links: int = 0  # of them, how many got a LinkedIn link
    emails: int = 0  # of them, how many got a verified email
    left: int = 0  # people still to ask about, past this run's limit

    def __add__(self, other: "Filled") -> "Filled":
        return Filled(
            self.tried + other.tried, self.links + other.links, self.emails + other.emails, self.left + other.left
        )


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


def _org_domain(hit: dict[str, Any]) -> str:
    raw = hit.get("organization")
    org: dict[str, Any] = raw if isinstance(raw, dict) else {}
    return host(str(org.get("primary_domain") or "")) or host(str(org.get("website_url") or ""))


def _same_company(company: str, domain: str | None, hit: dict[str, Any]) -> bool:
    raw = hit.get("organization")
    org: dict[str, Any] = raw if isinstance(raw, dict) else {}
    org_domain = _org_domain(hit)
    if org_domain:
        return bool(domain) and same_domain(org_domain, domain or "")
    # Apollo has no domain for the employer: its name must carry ours ("Phreesia Network Solutions" for Phreesia)
    ours, theirs = tokens(plain_name(company)), set(tokens(str(org.get("name") or "")))
    return bool(ours) and all(t in theirs for t in ours)


def _company_email(hit: dict[str, Any], domain: str | None) -> str | None:
    """Apollo's verified email, only at the company's own domain: an old employer's address is no use."""
    email = verified_email(hit)
    if email is None:
        return None
    at = email.rsplit("@", 1)[1]
    return email if any(d and same_domain(at, d) for d in (domain or "", _org_domain(hit))) else None


def verified_contact(name: str, company: str, domain: str | None, hit: dict[str, Any] | None) -> Contact:
    """Apollo's profile link and verified email for this person, only when the first name, the last name and the
    company all agree."""
    if not hit or not askable(name) or not _same_name(name, hit) or not _same_company(company, domain, hit):
        return Contact()
    return Contact(link=profile_link(hit.get("linkedin_url")), email=_company_email(hit, domain))


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


def _blank(value: str | None) -> bool:
    return not (value or "").strip()


def board_to_ask(person: Person) -> bool:
    """Still at the company, missing a link or an email, never asked about, and findable: a full name and the
    company's domain."""
    return (
        not person.left
        and (_blank(person.linkedin) or _blank(person.email))
        and not person.details.get("contact_tried")
        and bool(person.company.domain)
        and askable(person.name)
    )


def _board_todo(session: Session) -> Iterator[Person]:
    query = (
        select(Person)
        .join(Person.company)
        .where(
            Person.left.is_(False),  # what's missing is left to board_to_ask, the one place that decides it
            Company.domain.is_not(None),
            Company.domain != "",
        )
        .options(contains_eager(Person.company))
        .order_by(Person.created_at, Person.id)
    )
    for page in _pages(session, query):
        yield from (p for p in page if board_to_ask(p))


def _found_line(name: str, links: int, emails: int) -> str:
    bits = [f"LinkedIn for {_people(links)}"] if links else []
    bits += [f"verified emails for {_people(emails)}"] if emails else []
    return f"{name}: Apollo found " + " and ".join(bits)


def fill_board(session: Session, apollo: ContactFinder, today: date, limit: int) -> Filled:
    """Links and verified emails for people on the board, oldest first, up to `limit` people."""
    todo, more = _keep(_board_todo(session), max(limit, 0))
    tried = links = emails = 0
    for chunk in _chunks(todo, BULK):
        try:
            hits = apollo.bulk_match([_ask(p.name, p.company.name, p.company.domain, p.email) for p in chunk])
        except ApolloError:
            break  # Apollo is down or out of credits: the rest are asked about next time
        found: dict[tuple[str, str], Counter[str]] = {}
        for person, hit in zip(chunk, hits, strict=True):
            contact = verified_contact(person.name, person.company.name, person.company.domain, hit)
            # what was typed in during the lookup wins
            session.refresh(person, ["linkedin", "email", "details"], with_for_update=True)
            details = {**person.details, "contact_tried": today.isoformat()}
            got = found.setdefault((person.company_id, person.company.name), Counter())
            if contact.link and _blank(person.linkedin):
                person.linkedin = contact.link
                details["link_source"] = "apollo"
                got["links"] += 1
            if contact.email and _blank(person.email):
                person.email = contact.email
                details |= {"email_source": "apollo", "email_status": "verified"}
                got["emails"] += 1
            person.details = details
        for (company_id, name), got in found.items():
            if got:
                record(session, "research", _found_line(name, got["links"], got["emails"]), company_id=company_id)
        tried += len(chunk)
        links += sum(g["links"] for g in found.values())
        emails += sum(g["emails"] for g in found.values())
        session.commit()
    return Filled(tried=tried, links=links, emails=emails, left=more + len(todo) - tried)


# ----------------------------------------------------------------------------- the Fractional list


def _fractional_todo(session: Session) -> Iterator[tuple[Prospect, dict[str, Any]]]:
    """Each research person still missing a link or an email, newest prospects first. What's found lives in the
    prospect's `mine`, which the daily research sync never touches, so it outlasts the sync."""
    query = (
        select(Prospect).where(Prospect.domain.is_not(None)).order_by(Prospect.day.desc(), Prospect.rank, Prospect.id)
    )
    for page in _pages(session, query):
        for p in page:
            mine = p.mine or {}
            if (mine.get("status") or "open") in CLOSED:
                continue
            found_links, found_emails = mine.get("links") or {}, mine.get("emails") or {}
            asked = mine.get("contact_tried") or {}
            for person in (p.research or {}).get("people") or []:
                key, name = str(person.get("key") or ""), str(person.get("name") or "")
                missing = not (person.get("linkedin") or found_links.get(key)) or not found_emails.get(key)
                if key and missing and key not in asked and askable(name):
                    yield p, person


def fill_fractional(session: Session, apollo: ContactFinder, today: date, limit: int) -> Filled:
    """Links and verified emails for people on the Fractional list, up to `limit` people."""
    todo, more = _keep(_fractional_todo(session), max(limit, 0))
    tried = links = emails = 0
    for chunk in _chunks(todo, BULK):
        try:
            hits = apollo.bulk_match([_ask(str(x["name"]), p.name, p.domain) for p, x in chunk])
        except ApolloError:
            break
        results: dict[str, list[tuple[dict[str, Any], Contact]]] = {}
        prospects: dict[str, Prospect] = {}
        for (p, x), hit in zip(chunk, hits, strict=True):
            results.setdefault(p.id, []).append((x, verified_contact(str(x["name"]), p.name, p.domain, hit)))
            prospects[p.id] = p
        for pid, pairs in results.items():
            p = prospects[pid]
            session.refresh(p, ["mine"], with_for_update=True)  # a tick saved during the lookup stays
            mine = dict(p.mine or {})
            found_links, found_emails = dict(mine.get("links") or {}), dict(mine.get("emails") or {})
            asked = dict(mine.get("contact_tried") or {})
            got: Counter[str] = Counter()
            for person, contact in pairs:
                key = str(person["key"])
                asked[key] = today.isoformat()
                if contact.link and not (person.get("linkedin") or found_links.get(key)):
                    found_links[key] = contact.link
                    got["links"] += 1
                if contact.email and not found_emails.get(key):
                    found_emails[key] = contact.email
                    got["emails"] += 1
            p.mine = {**mine, "links": found_links, "emails": found_emails, "contact_tried": asked}
            if got:
                record(session, "fractional", _found_line(p.name, got["links"], got["emails"]))
            links, emails = links + got["links"], emails + got["emails"]
        tried += len(chunk)
        session.commit()
    return Filled(tried=tried, links=links, emails=emails, left=more + len(todo) - tried)


def fill(session: Session, apollo: ContactFinder, today: date, limit: int) -> Filled:
    """The board first (the people you're writing to now), then the Fractional list, up to `limit` people in all."""
    board = fill_board(session, apollo, today, limit)
    return board + fill_fractional(session, apollo, today, limit - board.tried)
