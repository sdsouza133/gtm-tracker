"""Who to write to at a company a refresh just added: LinkedIn's people search through treg, filtered by the company
and one title word at a time (LinkedIn rejects long OR filters). Each person's part in the hire is guessed from their
headline, and people who work somewhere else (consultants, investors, agency recruiters) are left out.
"""

import re
from dataclasses import dataclass
from typing import Any

from app.models import RoleInHire, Sureness
from app.radar.fit import norm, web_url
from app.treg import Caller, TregError

PROFILE_SEARCH = "harvestapi.linkedin.profile.search"
CALL_USD = 0.004  # treg's list price, the most one call can cost
SMALL_TEAM = 50  # fewer people than this: the founder is the one to write to
WORDS = ("GTM", "revenue operations", "growth")
SMALL_TEAM_WORDS = ("founder", "GTM", "growth")

RECRUITER = re.compile(r"recruit|talent acquisition|talent partner|sourcer|hiring across", re.IGNORECASE)
FOUNDER = re.compile(r"\b(?:co-?founder|founder|ceo|chief executive)\b", re.IGNORECASE)
OPS = re.compile(
    r"rev(?:enue)?\s*ops|revenue operations|sales op(?:eration)?s|marketing op(?:eration)?s"
    r"|(?:\bgtm\b|go[- ]to[- ]market)\s*(?:ops|operations|systems|engineer\w*|strategy)?",
    re.IGNORECASE,
)
GROWTH = re.compile(r"growth|marketing|demand gen|\bsales\b|revenue", re.IGNORECASE)
LEADER = re.compile(r"\b(?:vp|vice president|head|director|chief|cro|cmo|coo|svp|evp|president)\b", re.IGNORECASE)
MANAGER = re.compile(r"\b(?:manager|lead|leader)\b", re.IGNORECASE)
ELSEWHERE = re.compile(r"\bat\b|@", re.IGNORECASE)
RANK = {
    RoleInHire.HIRING_MANAGER: 0,
    RoleInHire.FOUNDER: 1,
    RoleInHire.RECRUITER: 2,
    RoleInHire.APPROVER: 3,
    RoleInHire.PEER: 4,
}


@dataclass(frozen=True)
class Lead:
    name: str
    title: str
    linkedin: str
    location: str
    role: RoleInHire
    sureness: Sureness
    why: str


def guess(headline: str, company: str) -> tuple[RoleInHire, Sureness] | None:
    """Their likely part in hiring a GTM engineer, from their LinkedIn headline; None when it's someone to skip."""
    if not headline.strip() or not norm(company):
        return None
    at = ELSEWHERE.search(headline)
    if at:  # "... at Orama | formerly Acme": the employer named first is where they work now
        employer = re.split(r"[|,·•]", headline[at.end() :], maxsplit=1)[0]
        named = norm(company) in norm(employer)
        if not named:
            return None  # works somewhere else
    else:
        named = norm(company) in norm(headline)
    sure = Sureness.LIKELY if named else Sureness.GUESS
    senior = bool(LEADER.search(headline))
    manages = senior or bool(MANAGER.search(headline))
    role: tuple[RoleInHire, Sureness] | None = None
    if RECRUITER.search(headline):
        role = RoleInHire.RECRUITER, sure
    elif FOUNDER.search(headline):
        role = (RoleInHire.FOUNDER, Sureness.LIKELY) if named else None  # a founder of what, otherwise?
    elif OPS.search(headline):
        if manages:
            role = RoleInHire.HIRING_MANAGER, Sureness.LIKELY if named and senior else Sureness.GUESS
        else:
            role = RoleInHire.PEER, sure
    elif GROWTH.search(headline) and manages:
        role = (RoleInHire.APPROVER if senior else RoleInHire.PEER), Sureness.GUESS
    return role


def _location(value: Any) -> str:
    return str(value.get("linkedinText") or "") if isinstance(value, dict) else str(value or "")


def pick(leads: list[Lead], want: int) -> list[Lead]:
    """The most useful few: the likely hiring manager first, at most one recruiter."""
    ranked = sorted(leads, key=lambda p: (RANK.get(p.role, 9), p.sureness is not Sureness.LIKELY, p.name))
    out: list[Lead] = []
    for p in ranked:
        if p.role is RoleInHire.RECRUITER and any(q.role is RoleInHire.RECRUITER for q in out):
            continue
        out.append(p)
    return out[:want]


def find(
    treg: Caller, company_linkedin: str, company: str, employees: int | None, want: int, max_usd: float
) -> tuple[list[Lead], float]:
    """Up to `want` people at the company and what the lookups cost. A call is made only when its whole list price
    still fits in `max_usd`; one failing call skips that title word, not the company."""
    if want <= 0:
        return [], 0.0
    words = SMALL_TEAM_WORDS if employees is not None and employees < SMALL_TEAM else WORDS
    seen: dict[str, Lead] = {}
    spent = 0.0
    for word in words:
        if spent + CALL_USD > max_usd + 1e-9:
            break
        try:
            answer = treg.call(
                PROFILE_SEARCH, query={"currentCompany": company_linkedin, "title": word, "page": "1"}, max_usd=CALL_USD
            )
        except TregError as e:
            spent += e.spent
            continue
        spent += answer.cost_usd
        elements = answer.body.get("elements") if isinstance(answer.body, dict) else None
        for p in elements if isinstance(elements, list) else []:
            if not isinstance(p, dict):
                continue
            url = web_url(str(p.get("linkedinUrl") or "")).split("?")[0]  # a malformed profile is skipped
            name = " ".join(str(p.get("name") or "").split())
            headline = " ".join(str(p.get("position") or p.get("headline") or "").split())
            role = guess(headline, company)
            if not url or not name or url in seen or role is None:
                continue
            seen[url] = Lead(
                name=name[:200],
                title=headline[:200],
                linkedin=url,
                location=_location(p.get("location"))[:200],
                role=role[0],
                sureness=role[1],
                why=f"Found by a refresh on LinkedIn; headline: {headline[:160]}",
            )
    return pick(list(seen.values()), want), spent
