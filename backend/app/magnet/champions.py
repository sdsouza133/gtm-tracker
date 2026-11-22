"""Build a champion report: people who used a company's product at one of its customers and just started at a new
company that fits its ICP. They are the strongest way into that company, so the report is worth sending cold.

1. Read the company's site and its customer pages (free); Claude works out the ICP and lists the customers and the
   people the site names.
2. Find each customer's LinkedIn page, then search LinkedIn for people who left those customers in the last 90 days.
3. Rule people out by the free checks in `traps`, then have Claude screen the rest against the ICP.
4. Read the work history of the few left, keep those who really worked at a customer and have left it, and grade
   them (A named on the site, B a role that used it, C anyone else who worked there).
5. Check whether the people the site names are still where they were: the watch list for next time.

Every paid call draws on the build's treg budget, and each step keeps back what the later steps need. A report built
before for the same company is reused: its customers' pages and its champions' histories aren't paid for again, and
its champions are marked as not new.
"""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from pydantic import SecretStr

from app.config import Settings
from app.magnet import traps
from app.magnet.brain import ICP, MOVERS, Brain, Customer, Customers, NamedChampion, Verdict
from app.magnet.build import Budget, BuildError, Progress
from app.magnet.linkedin import (
    HISTORY,
    LEADS_SEARCH,
    PRICE,
    History,
    Job,
    LinkedIn,
    LinkedInError,
    Mover,
    company_key,
    parse_mover,
)
from app.magnet.site import read_customers, read_site
from app.radar.fit import domain_of, linkedin_slug, web_url
from app.treg import Treg

TREG_CAP_USD = 0.60  # LinkedIn spend for one report; Claude's three calls are on top
COMPANY_LOOKUPS = 40
SEARCH_PAGES = 3
PAGE_SIZE = 25
HISTORY_LOOKUPS = 10
WATCH_LOOKUPS = 6
SKIPPED_KEPT = 200  # the people ruled out that the report lists by name
EVIDENCE_ORDER = {"case_study": 0, "testimonial": 1, "logo": 2, "mention": 3}
GRADE_ORDER = {"A": 0, "B": 1, "C": 2}


class Scout(Protocol):
    """Claude's part in a champion report (the real one is `Brain`)."""

    def icp(self, site: dict[str, Any], competitors: list[str]) -> ICP: ...

    def customers(self, site: dict[str, Any], company: str) -> Customers: ...

    def screen(self, headlines: list[str], icp: ICP, exclude: list[str], *, about: str = ...) -> dict[int, Verdict]: ...


@dataclass
class ChampionTools:
    """What a champion report talks to; tests swap in fakes."""

    read_site: Callable[[str], dict[str, Any]]
    read_customers: Callable[[str], dict[str, Any]]
    brain: Scout
    linkedin: LinkedIn


def champion_tools(settings: Settings) -> ChampionTools:
    """The real network. Raises (BrainError or TregError) naming the setting that's missing."""

    def secret(value: SecretStr | None) -> str:
        return value.get_secret_value() if value else ""

    return ChampionTools(
        read_site=read_site,
        read_customers=read_customers,
        brain=Brain(secret(settings.anthropic_api_key), settings.magnet_icp_model, settings.magnet_screen_model),
        linkedin=LinkedIn(Treg(secret(settings.treg_token))),
    )


@dataclass(frozen=True)
class ChampionSpec:
    company: str
    website: str
    before: dict[str, Any] | None = None  # the last report built for this company, if any


@dataclass
class Matched:
    """A customer, and its LinkedIn page when one was found."""

    name: str
    domain: str
    evidence: str
    linkedin: str = ""
    linkedin_name: str = ""
    industry: str = ""

    def report(self) -> dict[str, str]:
        return {
            "name": self.name,
            "domain": self.domain,
            "evidence": self.evidence,
            "linkedin": self.linkedin,
            "linkedin_name": self.linkedin_name,
            "industry": self.industry,
        }


def build_champions(
    spec: ChampionSpec, tools: ChampionTools, today: date, progress: Progress | None = None
) -> dict[str, Any]:
    """The finished report as plain data. Raises BuildError when there's nothing to build from: no customers on the
    site (before anything is paid for), or none of them on LinkedIn."""
    say = progress or (lambda _step, _info: None)
    budget = Budget(TREG_CAP_USD)
    before = spec.before or {}
    keep_for_checks = (HISTORY_LOOKUPS + WATCH_LOOKUPS) * PRICE[HISTORY]

    say("reading the website", {"website": spec.website})
    site = tools.read_site(spec.website)
    pages = tools.read_customers(spec.website)
    say("working out the customers and the ICP", {"pages": len(pages.get("pages") or [])})
    found = tools.brain.customers(pages, spec.company)
    customers = _customers(found.customers, spec)
    if not customers:
        raise BuildError(
            "The website doesn't show any customers, so there's no one to track. Try a company that names its "
            "customers (case studies, logos or quotes)."
        )
    icp = tools.brain.icp(site, [])  # only once there are customers to track: it's a paid call too

    say("finding the customers on LinkedIn", {"customers": len(customers)})
    keep = SEARCH_PAGES * PRICE[LEADS_SEARCH] + keep_for_checks
    matched = _match(customers, before, icp, tools.linkedin, budget, keep)
    pages_found = [m.linkedin for m in matched if m.linkedin]
    if not pages_found:
        raise BuildError("None of the customers on the website has a LinkedIn page we could match.")

    say("looking for people who left them", {"customers": len(pages_found)})
    movers, total = _movers(pages_found, found.title_keywords, tools.linkedin, budget, keep_for_checks)
    rules = _rules(spec, icp, found, matched)
    skips = Skips()
    passed, fits = _filter(movers, rules, spec, icp, tools.brain, skips, say)

    names = [(c.name, c.linkedin) for c in found.champions]
    champions, checked = _verified(fits, names, before, rules, tools.linkedin, budget, skips, say, today)
    say("checking the people the site names", {"named": len(found.champions)})
    prior = {str(c.get("key")) for c in before.get("champions") or [] if isinstance(c, dict)}
    watch = _watch(found, champions, rules, tools, icp, _rule_out(spec, icp), budget, skips, today, prior)
    champions.sort(key=_champion_order)

    grades = Counter(str(c.get("grade")) for c in champions)
    return {
        "kind": "champions",
        "company": spec.company,
        "website": spec.website,
        "domain": domain_of(spec.website),
        "built": today.isoformat(),
        "icp": icp.model_dump(exclude={"competitors"}),
        "customers": [m.report() for m in matched],
        "keywords": list(rules.keywords),
        "champions": champions,
        "watch": watch,
        "skipped": dict(skips.counts),
        "skipped_people": skips.people,
        "stats": {
            "customers": len(customers),
            "matched": len(pages_found),
            "movers": total,
            "read": len(movers),
            "after_rules": len(passed),
            "fit": len(fits),
            "checked": checked,
            "champions": len(champions),
            "grades": {g: grades.get(g, 0) for g in ("A", "B", "C")},
            "new": sum(1 for c in champions if c.get("new")),
            "repeat": bool(spec.before),  # built again: who was in the last report isn't new
            "watch": len(watch),
            "linkedin_usd": round(budget.spent, 4),
        },
    }


@dataclass
class Skips:
    """The people ruled out: how many for each reason, and (up to SKIPPED_KEPT) who."""

    counts: Counter[str] = field(default_factory=Counter)
    people: list[dict[str, str]] = field(default_factory=list)

    def add(self, m: Mover, reason: str) -> None:
        self.counts[reason] += 1
        if len(self.people) < SKIPPED_KEPT and not m.hidden:
            job = traps.main_job(m.jobs)
            now = f"{job.title} at {job.company}" if job else ""
            self.people.append({"name": m.name, "linkedin": m.url, "now": now, "reason": reason})


def _rules(spec: ChampionSpec, icp: ICP, found: Customers, matched: list[Matched]) -> traps.Rules:
    pages = [m.linkedin for m in matched if m.linkedin]
    names = [*(m.name for m in matched), *(m.linkedin_name for m in matched)]
    return traps.Rules(
        vendor=company_key(spec.company),
        competitors=frozenset(k for k in (company_key(c.name) for c in icp.competitors) if k),
        customers=frozenset(k for k in (company_key(n) for n in names) if k),
        customer_pages=frozenset(s for s in (linkedin_slug(p) for p in pages) if s),
        regions=traps.allowed_regions(icp.regions),
        keywords=tuple(found.title_keywords),
        sells_to_non_buyers=_sells_to_non_buyers(icp),
    )


def _filter(
    movers: list[Mover], rules: traps.Rules, spec: ChampionSpec, icp: ICP, brain: Scout, skips: Skips, say: Progress
) -> tuple[list[Mover], list[tuple[Mover, str]]]:
    """The free checks, then one Claude screen of those who pass. Returns who passed the checks, and who fits (with
    Claude's reason)."""
    seen: set[str] = set()
    passed: list[Mover] = []
    for m in movers:
        reason = traps.judge(m, rules, seen)
        seen.add(m.key)
        if reason:
            skips.add(m, reason)
        else:
            passed.append(m)
    if not passed:
        return passed, []
    say("screening against the ICP", {"people": len(passed)})
    verdicts = brain.screen([_headline(m) for m in passed], icp, _rule_out(spec, icp), about=MOVERS)
    fits: list[tuple[Mover, str]] = []
    for i, m in enumerate(passed):
        verdict = verdicts.get(i)
        if verdict and verdict.fit:
            fits.append((m, verdict.reason))
        else:
            skips.add(m, "not_icp")
    return passed, fits


def _verified(
    fits: list[tuple[Mover, str]],
    names: list[tuple[str, str]],
    before: dict[str, Any],
    rules: traps.Rules,
    linkedin: LinkedIn,
    budget: Budget,
    skips: Skips,
    say: Progress,
    today: date,
) -> tuple[list[dict[str, Any]], int]:
    """The champions: those who fit, checked against their work history (people named on the site and the newest
    moves first, at most HISTORY_LOOKUPS), and graded. Champions from the last report still in the same job are kept
    without paying for them again, marked not new; one who has moved again is checked afresh. Also how many
    histories were looked up."""
    fits = sorted(fits, key=lambda f: (not traps.named(f[0], None, names), _months_in(f[0]), f[0].name))
    prior = {str(c.get("key")): c for c in before.get("champions") or [] if isinstance(c, dict) and c.get("key")}
    reused = {m.key: prior[m.key] for m, _ in fits if _same_move(prior.get(m.key), m)}
    checking = [(m, why) for m, why in fits if m.key not in reused][:HISTORY_LOOKUPS]
    say("checking their work history", {"fit": len(fits), "checking": len(checking)})
    histories = _histories([m.url for m, _ in checking], linkedin, budget, WATCH_LOOKUPS * PRICE[HISTORY], today)
    checked = {m.key for m, _ in checking}
    champions: list[dict[str, Any]] = []
    for m, why in fits:
        if m.key in reused:
            champions.append(_brought_up_to_date(reused[m.key], m))
            continue
        if m.key not in checked:
            skips.add(m, "over_cap")
            continue
        history = histories.get(m.url)
        reason, verified = traps.verify(m, history, rules, today)
        if reason or verified is None:
            skips.add(m, reason or "not_verified")
            continue
        champions.append(
            {
                "key": m.key,
                "name": m.name,
                "linkedin": history.url if history and history.url else m.url,
                "location": m.location,
                "grade": traps.grade(verified, traps.named(m, history, names), rules.keywords),
                "new": True,
                "was": _role(verified.was),
                "now": _role(verified.now),
                "gap_months": verified.gap,
                "why": why,
            }
        )
    return champions, len(checking)


def _same_move(row: dict[str, Any] | None, m: Mover) -> bool:
    """Whether the last report's row for this person still describes the job the search shows now (the same
    company), so its paid-for history check still holds."""
    job = traps.main_job(m.jobs)
    if row is None or job is None:
        return False
    then = _now_of(row)
    there = Job(
        title="",
        company=str(then.get("company") or ""),
        company_linkedin=str(then.get("company_linkedin") or ""),
        industry="",
        months=0,
    )
    return traps.same_company(there, job)


def _brought_up_to_date(row: dict[str, Any], m: Mover) -> dict[str, Any]:
    """The last report's row for a champion still at the same company: not new, with their title, industry and time
    there as today's search shows them (a promotion since then shows its new title)."""
    job = traps.main_job(m.jobs)
    then = _now_of(row)
    if job is None:
        return {**row, "new": False}
    now = {**then, "title": job.title or then.get("title", ""), "months": job.months}
    if job.industry:
        now["industry"] = job.industry
    return {**row, "now": now, "new": False}


def _now_of(row: dict[str, Any]) -> dict[str, Any]:
    now = row.get("now")
    return now if isinstance(now, dict) else {}


def _rule_out(spec: ChampionSpec, icp: ICP) -> list[str]:
    """Who the screen rules out as a new employer: the company itself and its competitors."""
    return [spec.company, *[c.name for c in icp.competitors]]


def _champion_order(c: dict[str, Any]) -> tuple[int, int, str]:
    """A first, then B, then C; within a grade the newest move first."""
    return GRADE_ORDER.get(str(c.get("grade")), 3), int((c.get("now") or {}).get("months") or 0), str(c.get("name"))


def _sells_to_non_buyers(icp: ICP) -> bool:
    """Whether the ICP's buyers are investors, recruiters or universities, so those industries aren't ruled out."""
    text = " ".join([*icp.industries, *icp.titles, *icp.functions]).lower()
    return any(w in text for w in ("venture", "private equity", "investor", "recruit", "staffing", "universit"))


def _customers(found: list[Customer], spec: ChampionSpec) -> list[Matched]:
    """The customers Claude listed, each once, without the company itself, case studies first."""
    own = (company_key(spec.company), domain_of(spec.website))
    out: dict[str, Matched] = {}
    for c in sorted(found, key=lambda c: EVIDENCE_ORDER.get(c.evidence, 9)):
        key = company_key(c.name)
        domain = domain_of(c.domain) if "." in c.domain else ""
        if not key or key in out or key == own[0] or (domain and domain == own[1]):
            continue
        out[key] = Matched(name=c.name.strip(), domain=domain, evidence=c.evidence)
    return list(out.values())


def _match(
    customers: list[Matched], before: dict[str, Any], icp: ICP, linkedin: LinkedIn, budget: Budget, keep: float
) -> list[Matched]:
    """Each customer's LinkedIn page: last report's match when there is one, else a lookup, case studies first, at
    most COMPANY_LOOKUPS. Customers past that stay listed without a page."""
    known = {
        company_key(str(c.get("name") or "")): c
        for c in before.get("customers") or []
        if isinstance(c, dict) and c.get("linkedin")
    }
    for c in customers:
        old = known.get(company_key(c.name))
        if old:
            c.linkedin = str(old.get("linkedin") or "")
            c.linkedin_name = str(old.get("linkedin_name") or "")
            c.industry = str(old.get("industry") or "")
    wanted = [c.name for c in customers if not c.linkedin][:COMPANY_LOOKUPS]
    orgs, spent = linkedin.companies(wanted, icp.industries, budget.left(keep))
    budget.add(spent)
    for c in customers:
        org = orgs.get(c.name)
        if org and not c.linkedin:
            c.linkedin, c.linkedin_name, c.industry = org.linkedin, org.name, org.industry
    return customers


def _movers(
    pages: list[str], keywords: list[str], linkedin: LinkedIn, budget: Budget, keep: float
) -> tuple[list[Mover], int]:
    """People who left those customers in the last 90 days, and how many LinkedIn found in all. A search that fails
    partway keeps the people already read; one that reads nobody is an error."""
    try:
        movers, total, spent = linkedin.movers(pages, keywords, SEARCH_PAGES * PAGE_SIZE, budget.left(keep))
    except LinkedInError as e:
        budget.add(e.spent)
        movers = [m for m in (parse_mover(i) for i in e.read) if m]
        if not movers:
            raise BuildError(f"LinkedIn's people search failed: {e}") from e
        return movers, len(movers)
    budget.add(spent)
    return movers, total


def _histories(urls: list[str], linkedin: LinkedIn, budget: Budget, keep: float, today: date) -> dict[str, History]:
    """Work histories by profile URL. When every lookup fails, nobody can be verified, which the report shows."""
    try:
        found, spent = linkedin.history(urls, budget.left(keep), today)
    except LinkedInError as e:
        budget.add(e.spent)
        return {}
    budget.add(spent)
    return found


def _watch(
    found: Customers,
    champions: list[dict[str, Any]],
    rules: traps.Rules,
    tools: ChampionTools,
    icp: ICP,
    rule_out: list[str],
    budget: Budget,
    skips: Skips,
    today: date,
    prior: set[str],
) -> list[dict[str, str]]:
    """The people the site names who aren't champions already, or ruled out already by the search's checks. Still at
    the customer: the watch list. Moved a while ago, or not checked (no LinkedIn address on the site, or past the cap):
    listed as such. Moved lately: the same free checks, work-history checks and Claude screen as everyone else, since
    being named only decides the grade. Those who pass are added to `champions` as A, the rest to `skips`."""
    done = {str(c.get("name") or "").lower() for c in champions} | {p["name"].lower() for p in skips.people}
    named = [c for c in found.champions if c.name.strip() and c.name.lower() not in done]
    lookups = [c for c in named if _profile_url(c.linkedin)][:WATCH_LOOKUPS]
    histories = _histories([_profile_url(c.linkedin) for c in lookups], tools.linkedin, budget, 0.0, today)
    looked = {c.name for c in lookups}
    seen = {str(c.get("key")) for c in champions}
    out: list[dict[str, str]] = []
    moved: list[tuple[NamedChampion, Mover, traps.Verified]] = []
    for c in named:
        row = {"name": c.name, "title": c.title, "company": c.company, "linkedin": _profile_url(c.linkedin)}
        history = histories.get(row["linkedin"]) if c.name in looked else None
        if history is None:
            out.append({**row, "status": "unchecked" if c.name not in looked else "not_found", "now": ""})
            continue
        status, current = _watch_status(c, history, rules, today)
        if status or current is None:
            out.append({**row, "status": status or "still_there", "now": _job_line(current)})
            continue
        url = history.url or row["linkedin"]
        mover = Mover(key=url, url=url, name=c.name, location="", jobs=(current,), hidden=False)
        reason = traps.judge(mover, rules, seen)
        seen.add(mover.key)
        verified = None
        if not reason:  # their history must show the customer job, left lately enough, like everyone else's
            reason, verified = traps.verify(mover, history, rules, today)
        if reason or verified is None:
            skips.add(mover, reason or "not_verified")
        else:
            moved.append((c, mover, verified))
    champions.extend(_named_champions(moved, tools.brain, icp, rule_out, skips, prior))
    return out


def _watch_status(c: NamedChampion, history: History, rules: traps.Rules, today: date) -> tuple[str, Job | None]:
    """Where a named person is now, with their current job: "still_there" (still at a customer, or at the company the
    site names), "moved" (a while ago, or a new title where they've been for a while) or "" (they just moved)."""
    current_jobs = [j for j in history.jobs if j.end is None and not traps.side_role(j)]
    current = traps.main_job(current_jobs)
    if (
        current is None
        or any(traps.at_customer(j, rules) for j in current_jobs)
        or company_key(current.company) == company_key(c.company)
    ):
        return "still_there", current
    joined = traps.stint_start(history.jobs, current)
    if joined is None or _months_between(joined, today) > traps.MAX_MOVE_MONTHS + 1:  # the 90 days, give or take
        return "moved", current
    return "", current


def _named_champions(
    moved: list[tuple[NamedChampion, Mover, traps.Verified]],
    brain: Scout,
    icp: ICP,
    rule_out: list[str],
    skips: Skips,
    prior: set[str],
) -> list[dict[str, Any]]:
    """Named people who just moved and passed the free and work-history checks, screened against the ICP like
    everyone else: one Claude call, made only when there are any. Those who fit are champions, graded A for being
    named."""
    if not moved:
        return []
    verdicts = brain.screen([_headline(m) for _, m, _ in moved], icp, rule_out, about=MOVERS)
    out: list[dict[str, Any]] = []
    for i, (c, m, verified) in enumerate(moved):
        verdict = verdicts.get(i)
        if not (verdict and verdict.fit):
            skips.add(m, "not_icp")
            continue
        out.append(
            {
                "key": m.key,
                "name": c.name,
                "linkedin": m.url,
                "location": "",
                "grade": "A",
                "new": m.key not in prior,
                "was": _role(verified.was),
                "now": _role(verified.now),
                "gap_months": verified.gap,
                "why": f"Named on the site at {c.company or 'a customer'}. {verdict.reason}".strip(),
            }
        )
    return out


def _job_line(job: Job | None) -> str:
    return f"{job.title} at {job.company}" if job else ""


def _profile_url(value: str) -> str:
    """A LinkedIn profile address from what a site shows: a full address or a bare handle."""
    text = value.strip()
    if not text:
        return ""
    if "linkedin.com/in/" in text:
        return web_url(text if text.startswith("http") else "https://" + text.lstrip("/")).split("?")[0].rstrip("/")
    handle = text.lstrip("@").strip("/")
    return f"https://www.linkedin.com/in/{handle}" if handle and "/" not in handle and " " not in handle else ""


def _headline(m: Mover) -> str:
    job = traps.main_job(m.jobs)
    if job is None:
        return m.name
    industry = f" ({job.industry})" if job.industry else ""
    return f"{job.title} at {job.company}{industry}"


def _months_in(m: Mover) -> int:
    job = traps.main_job(m.jobs)
    return job.months if job else 99


def _months_between(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month


def _role(job: Job) -> dict[str, Any]:
    return {
        "title": job.title,
        "company": job.company,
        "company_linkedin": job.company_linkedin,
        "industry": job.industry,
        "start": job.start.isoformat() if job.start else None,
        "end": job.end.isoformat() if job.end else None,
        "months": job.months,
    }
