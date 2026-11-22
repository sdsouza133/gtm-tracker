"""Who, among the people who left a company's customers, is a champion worth naming: the checks, in order, and the
grade.

Everyone ruled out gets one reason, the first check that fails, so the report can say why each person was left out.
The free checks (`judge`, on what the people search returned) run before anything is paid for; `verify` then reads
the work history of the few that pass Claude's screen.
"""

import re
from dataclasses import dataclass
from datetime import date

from app.magnet.linkedin import History, Job, Mover, company_key
from app.radar.fit import linkedin_slug, norm

MAX_MOVE_MONTHS = 3  # LinkedIn's "changed jobs" is the last 90 days; longer in the new job is old news
MAX_GAP_MONTHS = 36  # left the customer this long before the new job: likely before the customer used the product
FRESH_GAP_MONTHS = 24  # a B champion left the customer no longer than this before the new job
MIN_CHAMPION_MONTHS = 6  # long enough at the customer to have used the product

SIDE = re.compile(
    r"\b(advis[eo]r\w*|advisory|board (member|director|observer)|board of (directors|advisors)|non[- ]executive|"
    r"investor|angel|venture (partner|scout)|fractional|freelanc\w*|self[- ]employed|"
    r"(independent|freelance) (consultant|advisor|contractor)|mentor|volunteer|ambassador|"
    r"entrepreneur in residence|career break|sabbatical|open to work)\b",
    re.IGNORECASE,
)
SELF_COMPANY = re.compile(r"^(self[- ]employed|freelance|independent|stealth\b.*|confidential)$", re.IGNORECASE)
JUNIOR = re.compile(
    r"\b(intern(ship)?|student|trainee|apprentice|junior|jr|coordinator|"
    r"assistant(?! (vice president|vp|general counsel|director))|"
    r"associate(?! (director|vice president|vp|general counsel|partner|principal)))\b",
    re.IGNORECASE,
)
LEADER = re.compile(
    r"\b(head|director|vp|vice president|chief|c[a-z]o|president|founder|co-?founder|owner|manager|lead)\b",
    re.IGNORECASE,
)
NON_BUYER_INDUSTRIES = frozenset(
    {"venture capital and private equity principals", "staffing and recruiting", "higher education"}
)

REASONS = {
    "hidden": "LinkedIn hides who they are",
    "duplicate": "Listed twice",
    "no_current_role": "No current job listed",
    "side_role": "Only a side role now (advisor, board, freelance...)",
    "joined_vendor": "Joined the company itself",
    "joined_competitor": "Joined a competitor",
    "joined_customer": "Moved to another customer, which already uses it",
    "junior": "Junior role",
    "stale_move": "Started the new job over 3 months ago",
    "outside_region": "Outside the ICP's regions",
    "non_buyer_industry": "An industry that doesn't buy it (VC, staffing, universities)",
    "not_icp": "The new company or role isn't in the ICP",
    "no_history": "Their work history couldn't be read",
    "not_verified": "Their work history shows no job at a customer",
    "still_at_customer": "Still works at the customer",
    "left_customer_long_ago": "Left the customer over 3 years before the new job",
    "internal_move": "A new title at a company they joined earlier",
    "over_cap": "Fits, but past this report's 10 work-history checks",
}

US_STATES = (
    "alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|georgia|hawaii|idaho|illinois|"
    "indiana|iowa|kansas|kentucky|louisiana|maine|maryland|massachusetts|michigan|minnesota|mississippi|missouri|"
    "montana|nebraska|nevada|new hampshire|new jersey|new mexico|new york|north carolina|north dakota|ohio|oklahoma|"
    "oregon|pennsylvania|rhode island|south carolina|south dakota|tennessee|texas|utah|vermont|virginia|washington|"
    "west virginia|wisconsin|wyoming|district of columbia|san francisco bay area"
)
CA_PROVINCES = (
    "ontario|quebec|british columbia|alberta|manitoba|saskatchewan|nova scotia|new brunswick|newfoundland|"
    "prince edward island"
)
COUNTRIES = {
    "united states": "US",
    "usa": "US",
    "canada": "CA",
    "mexico": "MX",
    "united kingdom": "GB",
    "england": "GB",
    "scotland": "GB",
    "wales": "GB",
    "ireland": "IE",
    "australia": "AU",
    "new zealand": "NZ",
    "india": "IN",
    "pakistan": "PK",
    "philippines": "PH",
    "singapore": "SG",
    "israel": "IL",
    "united arab emirates": "AE",
    "south africa": "ZA",
    "nigeria": "NG",
    "brazil": "BR",
    "argentina": "AR",
    "colombia": "CO",
    "germany": "DE",
    "france": "FR",
    "netherlands": "NL",
    "belgium": "BE",
    "spain": "ES",
    "portugal": "PT",
    "italy": "IT",
    "switzerland": "CH",
    "austria": "AT",
    "sweden": "SE",
    "norway": "NO",
    "denmark": "DK",
    "finland": "FI",
    "poland": "PL",
    "japan": "JP",
}
CITIES = {
    "london": "GB",
    "manchester": "GB",
    "melbourne": "AU",
    "sydney": "AU",
    "toronto": "CA",
    "vancouver": "CA",
    "montreal": "CA",
    "dublin": "IE",
    "bengaluru": "IN",
    "bangalore": "IN",
    "mumbai": "IN",
    "manila": "PH",
    "tel aviv": "IL",
    "berlin": "DE",
    "paris": "FR",
    "amsterdam": "NL",
}
EUROPE = frozenset({"GB", "IE", "DE", "FR", "NL", "BE", "ES", "PT", "IT", "CH", "AT", "SE", "NO", "DK", "FI", "PL"})
REGIONS = {
    "united states": {"US"},
    "usa": {"US"},
    "us": {"US"},
    "canada": {"CA"},
    "north america": {"US", "CA", "MX"},
    "united kingdom": {"GB"},
    "uk": {"GB"},
    "ireland": {"IE"},
    "europe": EUROPE,
    "emea": EUROPE | {"IL", "AE", "ZA", "NG"},
    "australia": {"AU"},
    "anz": {"AU", "NZ"},
    "apac": {"AU", "NZ", "IN", "SG", "PH", "JP"},
    "latin america": {"MX", "BR", "AR", "CO"},
    "latam": {"MX", "BR", "AR", "CO"},
}
ANYWHERE = re.compile(r"\b(global|worldwide|anywhere|international)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Rules:
    """What the checks compare against, from the company, its ICP and its customers."""

    vendor: str  # the company's own name, as `company_key` sees it
    competitors: frozenset[str]  # company keys
    customers: frozenset[str]  # company keys of its customers
    customer_pages: frozenset[str]  # its customers' LinkedIn company slugs
    regions: frozenset[str]  # ISO country codes people may be in; empty means anywhere
    keywords: tuple[str, ...] = ()  # words in the titles of the people who used it
    sells_to_non_buyers: bool = False  # its buyers are investors, recruiters or universities: keep those


def allowed_regions(regions: list[str]) -> frozenset[str]:
    """The ICP's regions (named regions like "Europe", or countries like "Germany") as country codes. Empty (no check)
    when it sells anywhere or names no place we know."""
    codes: set[str] = set()
    for region in regions:
        text = region.lower()
        if ANYWHERE.search(text):
            return frozenset()
        for name, countries in REGIONS.items():
            if re.search(rf"\b{re.escape(name)}\b", text):
                codes |= countries
        for name, code in COUNTRIES.items():  # our own table's names, escaped: no pattern comes from the ICP
            if re.search(rf"\b{re.escape(name)}\b", text):
                codes.add(code)
    return frozenset(codes)


def country_of(location: str) -> str:
    """The country a LinkedIn location names ("Atlanta, Georgia, United States" is US), or "" when it doesn't say
    ("Los Angeles Metropolitan Area")."""
    text = (location or "").lower()
    if not text:
        return ""
    for part in reversed([p.strip() for p in text.split(",")]):
        if part in COUNTRIES:
            return COUNTRIES[part]
    for name, code in COUNTRIES.items():
        if re.search(rf"\b{name}\b", text):
            return code
    if re.search(rf"\b({US_STATES})\b", text):
        return "US"
    if re.search(rf"\b({CA_PROVINCES})\b", text):
        return "CA"
    return next((code for city, code in CITIES.items() if re.search(rf"\b{city}\b", text)), "")


def side_role(job: Job) -> bool:
    return bool(SIDE.search(job.title) or SELF_COMPANY.match(job.company.strip()))


def main_job(jobs: tuple[Job, ...] | list[Job]) -> Job | None:
    """The job that counts: the first current one that isn't a side role (a board seat, advising, freelance)."""
    return next((j for j in jobs if (j.title or j.company) and not side_role(j)), None)


def at_customer(job: Job, rules: Rules) -> bool:
    page = linkedin_slug(job.company_linkedin)
    return bool(page and page in rules.customer_pages) or company_key(job.company) in rules.customers


def same_company(a: Job, b: Job) -> bool:
    """Whether two jobs are at the same company: the same name (as `company_key` reads it) or the same LinkedIn page.
    Either can differ between sources (a page by number or by name, a name with or without "Inc."): either will do."""
    key = company_key(a.company)
    if key and key == company_key(b.company):
        return True
    page = linkedin_slug(a.company_linkedin)
    return bool(page) and page == linkedin_slug(b.company_linkedin)


def stint_start(jobs: tuple[Job, ...] | list[Job], now: Job) -> date | None:
    """When their current run at `now`'s company began: back across their earlier titles there (promotions), until
    they worked somewhere else in between. Someone who comes back after a job elsewhere starts a new run."""
    start = now.start
    if start is None:
        return None
    others = [j.start for j in jobs if j.start is not None and not side_role(j) and not same_company(j, now)]
    earlier = sorted(  # their earlier jobs there, newest first: when each began and ended
        (
            (j.start, j.end or j.start)
            for j in jobs
            if j.start is not None and j.start < start and not side_role(j) and same_company(j, now)
        ),
        reverse=True,
    )
    for began, left in earlier:
        if any(left <= other < start for other in others):  # a job elsewhere began in between: a new run
            break
        start = began
    return start


def judge(m: Mover, rules: Rules, seen: set[str]) -> str | None:
    """The first free check this person fails, or None when they pass them all. `seen` is the people already judged
    in this build."""
    if m.hidden:
        return "hidden"
    if m.key in seen:
        return "duplicate"
    jobs = [j for j in m.jobs if j.title or j.company]
    if not jobs:
        return "no_current_role"
    job = main_job(jobs)
    if job is None:
        return "side_role"
    company = company_key(job.company)
    country = country_of(m.location)
    checks = (  # in order: the first that fails is the reason
        ("joined_vendor", bool(company) and company == rules.vendor),
        ("joined_competitor", bool(company) and company in rules.competitors),
        ("joined_customer", at_customer(job, rules)),
        ("junior", bool(JUNIOR.search(job.title))),
        ("stale_move", job.months > MAX_MOVE_MONTHS),
        ("outside_region", bool(rules.regions and country and country not in rules.regions)),
        ("non_buyer_industry", not rules.sells_to_non_buyers and job.industry.lower() in NON_BUYER_INDUSTRIES),
    )
    return next((reason for reason, failed in checks if failed), None)


def _months(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month


@dataclass(frozen=True)
class Verified:
    was: Job  # their last job at a customer
    now: Job  # the new job, with its dates from the history
    gap: int  # months between leaving the customer and starting the new job


def verify(m: Mover, history: History | None, rules: Rules, today: date) -> tuple[str | None, Verified | None]:
    """Their work history checked: they worked at a customer, have left it, and the new job is a real move. The first
    failing reason, or None with what was found."""
    if history is None or not history.jobs:
        return "no_history", None
    customer_jobs = [j for j in history.jobs if at_customer(j, rules) and not side_role(j)]
    if not customer_jobs:
        return "not_verified", None
    if any(j.end is None for j in customer_jobs):
        return "still_at_customer", None
    was = max(customer_jobs, key=lambda j: (j.end or date.min, j.start or date.min))
    found = main_job(m.jobs)
    current = [j for j in history.jobs if j.end is None and not side_role(j) and not at_customer(j, rules)]
    # only the job the search found counts: it's the one the checks and the screen passed, so no other is guessed
    here = [j for j in current if found and same_company(j, found)]
    if not found or not here:
        return "not_verified", None
    joined = stint_start(history.jobs, here[0])
    now = Job(  # the search knows the company's page and industry; the history knows the dates
        title=here[0].title or found.title,
        company=here[0].company or found.company,
        company_linkedin=here[0].company_linkedin or found.company_linkedin,
        industry=found.industry,
        months=here[0].months,
        start=here[0].start,
        end=None,
    )
    gap = _months(was.end, now.start) if was.end and now.start else 0
    late = joined is not None and _months(joined, today) > MAX_MOVE_MONTHS + 1  # LinkedIn's 90 days, give or take
    reason = "left_customer_long_ago" if gap > MAX_GAP_MONTHS else "internal_move" if late else None
    return (reason, None) if reason else (None, Verified(was=was, now=now, gap=max(0, gap)))


def named(m: Mover, history: History | None, champions: list[tuple[str, str]]) -> bool:
    """Whether the site names this person: same name, or the same LinkedIn address. `champions` holds (name,
    linkedin) pairs."""
    name = norm(m.name)
    urls = {u.rstrip("/").lower() for u in (m.url, history.url if history else "") if u}
    for their_name, their_linkedin in champions:
        if name and norm(their_name) == name:
            return True
        handle = their_linkedin.rstrip("/").lower().rsplit("/", 1)[-1]
        if handle and any(u.endswith("/" + handle) for u in urls):
            return True
    return False


def grade(v: Verified, is_named: bool, keywords: tuple[str, ...]) -> str:
    """A: the site names them. B: they held a role that uses the product (its title words, or a leader's) at the
    customer for long enough, and left it lately. C: anyone else who verifiably worked there."""
    if is_named:
        return "A"
    title = v.was.title.lower()
    fits_title = any(k.lower() in title for k in keywords if k) or bool(LEADER.search(title))
    if fits_title and v.was.months >= MIN_CHAMPION_MONTHS and v.gap <= FRESH_GAP_MONTHS:
        return "B"
    return "C"
