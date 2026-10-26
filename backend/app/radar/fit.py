"""Does a role fit? Pure rules over titles, locations, pay and posting text; no network, no database."""

import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

# how close a title is to the target role: 3 = the role itself, 2 = next door, 1 = worth a look
TITLE_RULES = [
    (
        3,
        r"\bgtm\b.*\b(engineer|engineering|systems|automation|architect)"
        r"|go[- ]to[- ]market\s+(engineer|systems|automation)|growth\s+engineer"
        r"|revenue\s+(engineer|systems\s+engineer)",
    ),
    (
        3,
        r"\b(ai|automation)\b.*\b(gtm|revenue|sales|marketing)\b.*\b(engineer|ops|operations)"
        r"|\b(gtm|revenue|sales)\b.*\bai\b.*\b(engineer|ops|operations)",
    ),
    (
        2,
        r"\brev(enue)?\s*ops\b|revenue\s+operations|sales\s+operations|marketing\s+operations"
        r"|gtm\s+(operations|ops|strategy)|growth\s+(operations|ops)",
    ),
    (
        2,
        r"\b(sales|marketing|revenue|gtm)\s+(systems|automation|technology|tech)\b"
        r"|business\s+systems\s+(analyst|engineer|manager).*\b(gtm|sales|revenue)",
    ),
    (
        1,
        r"\b(salesforce|hubspot|crm)\b.*\b(admin|administrator|developer|engineer|architect|manager)\b"
        r"|demand\s+gen\w*\s+(ops|operations)|lifecycle\s+(ops|operations)",
    ),
]
SKIP_TITLE = re.compile(r"\b(intern|internship|co-?op|recruit\w*|talent)\b", re.IGNORECASE)
OVERSEAS = re.compile(
    r"\b(sydney|melbourne|australia|london|united kingdom|barcelona|madrid|spain|berlin|munich|germany|paris|france|"
    r"amsterdam|netherlands|dublin|ireland|india|bangalore|bengaluru|hyderabad|singapore|tel aviv|israel|lisbon|"
    r"portugal|warsaw|poland|stockholm|zurich|tokyo|emea|apac)\b",
    re.IGNORECASE,
)
AGENCY = re.compile(
    r"\b(staffing|recruit\w*|headhunt\w*|talent (partners|solutions|acquisition)|jobgether|jobot|dice|hired|lensa)\b",
    re.IGNORECASE,
)
NEEDS_US = re.compile(
    r"authori[sz]ed to work in the (united states|u\.?s\.?a?)\b"
    r"|without (the need for )?(current or future )?(employer |visa )?sponsorship"
    r"|\b(u\.?s\.?|united states) citizen(ship)?\b|security clearance|green card"
    r"|\((?:remote[^)]*)?(?:u\.?s\.?a?|united states)[- ]based\)"
    r"|\bmust (?:be )?(?:located|based|reside|live) in the (?:u\.?s\.?a?|united states)\b"
    r"|\b(?:u\.?s\.?|united states) residents? only\b"
    r"|currently (?:based|located|residing) in the (?:u\.?s\.?a?|united states)\b"
    r"|\bremote\s*[(\-:,]\s*(?:u\.?s\.?a?|united states)\b(?!\s*(?:or|/|and|,)\s*canada)",
    re.IGNORECASE,
)
CANADA = re.compile(
    r"\b(canada|toronto|ontario|vancouver|montr[eé]al|ottawa|calgary|waterloo|mississauga|british columbia|quebec)\b",
    re.IGNORECASE,
)
REMOTE = re.compile(r"\bremote\b", re.IGNORECASE)
SALARY = re.compile(
    r"(?:US|CA)?\$\s?\d{2,3}(?:,\d{3}|[kK])(?:\.\d+)?\s*(?:-|–|to)\s*(?:US|CA)?\$?\s?\d{2,3}(?:,\d{3}|[kK])(?:\.\d+)?",
    re.IGNORECASE,
)
CORE = re.compile(
    r"\b(gtm|go[- ]to[- ]market)\b[^,|(]*\b(engineer|engineering|automation|architect)\b"
    r"|\b(engineer|engineering)\b[^|(]*\b(gtm|go[- ]to[- ]market)\b",
    re.IGNORECASE,
)
NOT_CORE = re.compile(r"\b(analyst|administrator|admin|specialist|coordinator|intern)\b", re.IGNORECASE)
COUNTRY_WIDE = re.compile(r"^\s*(united states|usa?|u\.s\.a?\.?|north america|americas|anywhere)\s*$", re.IGNORECASE)
ONSITE = re.compile(r"\b(on-?sites?|in[- ]office|in person|hybrid|relocat\w*)\b", re.IGNORECASE)
MONEY = re.compile(r"(CA\$|C\$|CAD|US\$|USD|\$)\s?(\d{2,3}(?:,\d{3})?(?:\.\d+)?)\s*([kK])?")
FULLY_REMOTE = re.compile(r"\b(fully remote|remote[- ]first|100% remote)\b", re.IGNORECASE)
HOURLY = re.compile(r"/\s*(hr|hour)|per hour|hourly", re.IGNORECASE)
USD_NAMED = re.compile(r"\bUSD\b|US\s?\$", re.IGNORECASE)
THOUSAND = 1000


@dataclass(frozen=True)
class RadarConfig:
    """What the radar looks for. Stored in settings under `radar_config`; anything missing takes these defaults."""

    keywords: list[str] = field(
        default_factory=lambda: [
            "GTM Engineer",
            "Go To Market Engineer",
            "GTM Engineering",
            "GTM Automation",
            "Founding GTM Engineer",
        ]
    )
    locations: list[str] = field(default_factory=lambda: ["United States", "Canada"])
    per_search: int = 25  # most jobs taken from each keyword x location search
    daily_usd: float = 0.30  # Apify stops the LinkedIn run at this spend
    hour: int = 7  # local hour the morning run starts
    min_fit: int = 2  # 3 = the role itself, 2 = next door (RevOps, GTM systems), 1 = worth a look
    recent_days: int = 7  # a role older than this is likely filled
    ats_search: bool = True  # also search company job boards through Google
    post_search: bool = True  # also search LinkedIn posts where people say they're hiring
    core_only: bool = True  # only GTM engineering roles, not RevOps, admin or analyst
    toronto_ok: bool = True  # only roles workable from Toronto: remote in the US or North America, or in Canada
    min_usd: int = 100_000  # the top of a listed USD range must reach this
    min_cad: int = 137_000  # the same for a CAD range

    @classmethod
    def from_setting(cls, value: Any) -> "RadarConfig":
        if not isinstance(value, dict):
            return cls()
        known = {k: v for k, v in value.items() if k in cls.__dataclass_fields__ and v not in (None, "", [])}
        return cls(**known)


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def domain_of(url: str) -> str:
    u = re.sub(r"^https?://", "", (url or "").strip().lower()).removeprefix("www.")
    return u.split("/")[0].split("?")[0]


def web_url(url: str | None) -> str:
    """The link if it's http(s), else "": job data comes from outside and ends up in an href."""
    u = (url or "").strip()
    return u[:1000] if re.match(r"https?://", u, re.IGNORECASE) else ""


def linkedin_slug(url: str) -> str:
    m = re.search(r"linkedin\.com/company/([^/?#]+)", url or "")
    return urllib.parse.unquote(m.group(1)).lower() if m else ""


def title_score(title: str) -> int:
    if not title or SKIP_TITLE.search(title):
        return 0
    t = title.lower()
    return max((score for score, rx in TITLE_RULES if re.search(rx, t)), default=0)


def core_role(title: str) -> bool:
    return bool(CORE.search(title or "")) and not NOT_CORE.search(title or "")


def workable_from_toronto(location: str, text: str = "") -> bool:
    """Remote in the US or North America, anywhere in Canada, or a country-wide US listing (LinkedIn's remote roles)."""
    if CANADA.search(location or ""):
        return True
    if NEEDS_US.search(text or "") or NEEDS_US.search(location or ""):
        return False
    remote = bool(REMOTE.search(location or "") and not ONSITE.search(location or ""))
    return remote or bool(COUNTRY_WIDE.match(location or ""))


def pay_ok(salary: str, cfg: RadarConfig, canadian: bool = False) -> bool:
    """The top of the listed range reaches the floor. No salary listed passes; hourly pay is left to you. A plain "$"
    on a Canadian posting is Canadian dollars unless it says USD or US$."""
    if not salary or HOURLY.search(salary):
        return True
    values = []
    for currency, number, k in MONEY.findall(salary):
        n = float(number.replace(",", ""))
        values.append((n * (THOUSAND if k or n < THOUSAND else 1), currency.upper().startswith("C")))
    if not values:
        return True
    top = max(values)[0]
    cad = any(c for _, c in values) or "CAD" in salary.upper()
    if canadian and not USD_NAMED.search(salary):
        cad = True
    return top >= (cfg.min_cad if cad else cfg.min_usd)


def fits(job: dict[str, Any], cfg: RadarConfig) -> tuple[bool, str]:
    """(fits, why not): the role, the place and the pay. Works for a board posting or a LinkedIn job."""
    if cfg.core_only and not core_role(job.get("title", "")):
        return False, "not a GTM engineering role"
    location = job.get("location") or ""
    if cfg.toronto_ok:
        us_only = "us_only" in (job.get("flags") or []) and not CANADA.search(location)
        if us_only or not workable_from_toronto(location, job.get("snippet") or job.get("text") or ""):
            return False, "on-site in the US, or US-only"
    if not pay_ok(job.get("salary") or "", cfg, bool(CANADA.search(location))):
        return False, "pay under the floor"
    return True, ""


def is_overseas(job: dict[str, Any]) -> bool:
    """Outside the US and Canada (India, Singapore, Europe...)."""
    return bool(OVERSEAS.search(job.get("location") or "")) and "canada" not in (job.get("flags") or [])


def flags_for(location: str, text: str) -> list[str]:
    flags = []
    if CANADA.search(location or ""):
        flags.append("canada")
    if REMOTE.search(location or "") or FULLY_REMOTE.search(text or ""):
        flags.append("remote")
    if NEEDS_US.search(text or ""):
        flags.append("us_only")
    return flags


def salary_in(text: str) -> str:
    m = SALARY.search(text or "")
    return m.group(0) if m else ""
