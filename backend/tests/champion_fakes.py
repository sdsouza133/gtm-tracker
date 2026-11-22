"""A made-up market for champion-report tests: a CX vendor's customers, the people who left them, and their work
histories, all answered through a fake treg. Every company and person here is invented."""

from datetime import date
from typing import Any

from app.magnet.brain import ENGAGERS, ICP, Competitor, Customer, Customers, NamedChampion, Verdict
from app.magnet.champions import ChampionTools
from app.magnet.linkedin import COMPANY_SEARCH, HISTORY, LEADS_SEARCH, LinkedIn
from tests.treg_fakes import FakeTreg

TODAY = date(2026, 11, 22)
VENDOR = "CXHero"
PRICES = {COMPANY_SEARCH: 0.002, LEADS_SEARCH: 0.05, HISTORY: 0.0015}  # what treg charged in the Nov 22 trial


def page(slug: str) -> str:
    return f"https://www.linkedin.com/company/{slug}"


def person(slug: str) -> str:
    return f"https://www.linkedin.com/in/{slug}"


def champion_icp() -> ICP:
    return ICP(
        company=VENDOR,
        sells="AI agents that answer customer service for consumer brands",
        industries=["Consumer brands", "Retail", "Personal care", "Food and beverage"],
        company_sizes=["11-500"],
        regions=["United States", "Canada"],
        titles=["VP Customer Experience", "Head of Support"],
        seniority=["Director", "VP"],
        functions=["Customer Experience", "Support"],
        exclude=[],
        competitors=[Competitor(name="Rival CX", domain="rivalcx.example", why="Same buyers")],
    )


CUSTOMERS = Customers(
    customers=[
        Customer(name="Glowco", domain="glowco.example", evidence="case_study"),
        Customer(name="Shoebird", domain="", evidence="case_study"),
        Customer(name="Mugworth", domain="", evidence="testimonial"),
        Customer(name="Pillow Lane", domain="", evidence="logo"),
        Customer(name="Ghost Co", domain="", evidence="logo"),
        Customer(name=VENDOR, domain="cxhero.example", evidence="mention"),  # the vendor itself: dropped
    ],
    champions=[
        NamedChampion(name="Dana Named", title="Senior Manager, CX", company="Glowco", linkedin="dana-named"),
        NamedChampion(name="Wren Stays", title="Head of Support", company="Shoebird", linkedin="@wren-stays"),
        NamedChampion(name="Moe Moved", title="Support Lead", company="Mugworth", linkedin=person("moe-moved")),
        NamedChampion(name="Kai Nolink", title="CX Lead", company="Pillow Lane", linkedin=""),
    ],
    title_keywords=["Customer Experience", "Support"],
)


class FakeScout:
    """Claude, made up: the ICP above, the given customer list, and a screen that turns down law firms and banks."""

    def __init__(self, customers: Customers = CUSTOMERS) -> None:
        self.found = customers
        self.screened: list[list[str]] = []
        self.abouts: list[str] = []
        self.icp_calls = 0

    def icp(self, site: dict[str, Any], competitors: list[str]) -> ICP:  # noqa: ARG002
        self.icp_calls += 1
        return champion_icp()

    def customers(self, site: dict[str, Any], company: str) -> Customers:  # noqa: ARG002
        return self.found

    def screen(
        self,
        headlines: list[str],
        icp: ICP,  # noqa: ARG002
        exclude: list[str],  # noqa: ARG002
        *,
        about: str = ENGAGERS,
    ) -> dict[int, Verdict]:
        self.screened.append(headlines)
        self.abouts.append(about)
        return {
            i: Verdict(i=i, fit=not any(w in h for w in ("Law", "Bank")), reason="runs CX at a consumer brand")
            for i, h in enumerate(headlines)
        }


def org(name: str, slug: str, industry: str, followers: str = "1K followers") -> dict[str, Any]:
    return {"name": name, "linkedinUrl": page(slug) + "/", "industry": industry, "followers": followers}


ORGS: dict[str, list[dict[str, Any]]] = {
    # two pages share the name: the one in the ICP's industries wins over the bigger one
    "Glowco": [
        org("Glowco Mining", "glowco-mining", "Mining", "50K followers"),
        org("Glowco Inc.", "glowco", "Personal Care Product Manufacturing", "12K followers"),
    ],
    "Shoebird": [org("Shoebird", "shoebird", "Retail Apparel and Fashion")],
    "Mugworth": [org("Mugworth Coffee", "mugworth", "Food and Beverage Services")],  # the name plus a word
    "Pillow Lane": [org("Pillow Lane", "pillowlane", "Retail")],
    "Ghost Co": [org("Ghostly Labs", "ghostly", "Software Development")],  # not the same company
}


def position(title: str, company: str, industry: str = "Retail", months: int = 1, slug: str = "") -> dict[str, Any]:
    entity = {"name": company, "industry": industry}
    if slug:
        entity["linkedinUrl"] = page(slug)
    return {
        "title": title,
        "companyName": company,
        "current": True,
        "tenureAtPosition": {"numYears": months // 12, "numMonths": months % 12},
        "company": entity,
    }


def mover(
    slug: str, name: str, *positions: dict[str, Any], location: str = "Austin, Texas, United States"
) -> dict[str, Any]:
    first, _, last = name.partition(" ")
    return {
        "id": f"id-{slug}",
        "linkedinUrl": person(slug),
        "firstName": first,
        "lastName": last,
        "location": {"linkedinText": location},
        "currentPositions": list(positions),
    }


PEOPLE: list[dict[str, Any]] = [
    mover("dana-named", "Dana Named", position("VP Customer Experience", "Newbrand", "Retail", 2)),
    mover("riley-lead", "Riley Lead", position("Head of CX", "Sockfox", "Retail Apparel and Fashion", 1)),
    mover("sam-rep", "Sam Rep", position("Customer Experience Specialist", "Lampkin", "Retail", 2)),
    {"id": "id-hidden", "firstName": "LinkedIn", "lastName": "Member", "currentPositions": [position("VP", "X")]},
    mover("riley-lead", "Riley Lead", position("Head of CX", "Sockfox", "Retail Apparel and Fashion", 1)),
    mover("nora-norole", "Nora Norole"),
    mover("ava-advisor", "Ava Advisor", position("Advisor", "Someco", "Retail", 1)),
    mover("vic-vendor", "Vic Vendor", position("Head of Partnerships", VENDOR, "Software Development", 1)),
    mover("cole-rival", "Cole Rival", position("Head of CX", "Rival CX", "Software Development", 1)),
    mover("cara-customer", "Cara Customer", position("Head of CX", "Pillow Lane", "Retail", 1, slug="pillowlane")),
    mover("ian-intern", "Ian Intern", position("Customer Experience Intern", "Bramble", "Retail", 1)),
    mover("stu-stale", "Stu Stale", position("Head of CX", "Thistle", "Retail", 5)),
    mover(
        "lon-don", "Lon Don", position("Head of CX", "Teacup", "Retail", 1), location="London, England, United Kingdom"
    ),
    mover("vera-vc", "Vera Vc", position("Partner", "Acorn", "Venture Capital and Private Equity Principals", 1)),
    mover("lena-law", "Lena Law", position("Director of CX", "Smith Law Firm", "Law Practice", 1)),
    mover("ned-nohistory", "Ned Nohistory", position("Head of CX", "Pebble", "Retail", 1)),
    mover("una-unverified", "Una Unverified", position("Head of CX", "Quill", "Retail", 1)),
    mover("stella-still", "Stella Still", position("VP CX", "Maple", "Retail", 1)),
    mover("gus-gap", "Gus Gap", position("Head of CX", "Juniper", "Retail", 1)),
    mover("ivy-internal", "Ivy Internal", position("Director of CX", "Birch", "Retail", 1)),
]


def job(title: str, company: str, slug: str, start: tuple[int, int], end: tuple[int, int] | None) -> dict[str, Any]:
    return {
        "jobTitle": title,
        "company": {"url": page(slug) + "/", "name": company},
        "timePeriod": {
            "startDate": {"year": start[0], "month": start[1]},
            "endDate": {"year": end[0], "month": end[1]} if end else None,
        },
    }


def history(slug: str, *jobs: dict[str, Any]) -> dict[str, Any]:
    return {"publicIdentifier": slug, "url": person(slug) + "/", "experiences": list(jobs)}


HISTORIES: dict[str, dict[str, Any]] = {
    person("dana-named"): history(
        "dana-named",
        job("VP Customer Experience", "Newbrand", "newbrand", (2026, 9), None),
        job("Senior Manager, Customer Experience", "Glowco Inc.", "glowco", (2021, 3), (2026, 8)),
    ),
    person("riley-lead"): history(
        "riley-lead",
        job("Head of CX", "Sockfox", "sockfox", (2026, 10), None),
        job("Director of Customer Experience", "Shoebird", "shoebird", (2022, 1), (2026, 8)),
    ),
    person("sam-rep"): history(
        "sam-rep",
        job("Customer Experience Specialist", "Lampkin", "lampkin", (2026, 9), None),
        job("CX Associate", "Shoebird", "shoebird", (2025, 3), (2025, 9)),
    ),
    person("ned-nohistory"): {"experiences": []},
    person("una-unverified"): history(
        "una-unverified",
        job("Head of CX", "Quill", "quill", (2026, 10), None),
        job("CX Manager", "Elsewhere", "elsewhere", (2020, 1), (2026, 9)),
    ),
    person("stella-still"): history(
        "stella-still",
        job("VP CX", "Maple", "maple", (2026, 10), None),
        job("Customer Experience Lead", "Glowco Inc.", "glowco", (2023, 1), None),
    ),
    person("gus-gap"): history(
        "gus-gap",
        job("Head of CX", "Juniper", "juniper", (2026, 10), None),
        job("Support Manager", "Mugworth Coffee", "mugworth", (2015, 1), (2019, 12)),
    ),
    person("ivy-internal"): history(
        "ivy-internal",
        job("Director of CX", "Birch", "birch", (2026, 10), None),
        job("CX Manager", "Birch", "birch", (2024, 2), (2026, 10)),
        job("Support Lead", "Pillow Lane", "pillowlane", (2021, 1), (2024, 1)),
    ),
    person("wren-stays"): history("wren-stays", job("Head of Support", "Shoebird", "shoebird", (2020, 5), None)),
    person("moe-moved"): history(
        "moe-moved",
        job("Head of Support", "Figleaf", "figleaf", (2026, 10), None),
        job("Support Lead", "Mugworth Coffee", "mugworth", (2022, 6), (2026, 9)),
    ),
}


def market(
    orgs: dict[str, list[dict[str, Any]]] | None = None,
    movers: list[dict[str, Any]] | None = None,
    histories: dict[str, dict[str, Any]] | None = None,
    *,
    fail: set[str] | None = None,
) -> FakeTreg:
    """treg answering from the made-up market: company search by name, the people search a page of 25 at a time,
    and work histories by profile."""
    found_orgs = ORGS if orgs is None else orgs
    found_movers = PEOPLE if movers is None else movers
    found_histories = HISTORIES if histories is None else histories

    def companies(query: dict[str, Any], _body: dict[str, Any] | None) -> dict[str, Any]:
        return {"elements": found_orgs.get(str(query.get("search")), [])}

    def leads(query: dict[str, Any], _body: dict[str, Any] | None) -> dict[str, Any]:
        n = int(query.get("page") or 1)
        size = 25
        rows = found_movers[(n - 1) * size : n * size]
        pages = max(1, -(-len(found_movers) // size))
        return {"elements": rows, "pagination": {"totalElements": len(found_movers), "totalPages": pages}}

    def histories_by(query: dict[str, Any], _body: dict[str, Any] | None) -> dict[str, Any]:
        return found_histories.get(str(query.get("profileUrlOrUrn")), {})

    return FakeTreg({COMPANY_SEARCH: companies, LEADS_SEARCH: leads, HISTORY: histories_by}, prices=PRICES, fail=fail)


def pages_read(_: str) -> dict[str, Any]:
    return {"url": "https://cxhero.example", "pages": ["https://cxhero.example/customers"], "text": "Customers: ..."}


def tools(scout: FakeScout | None = None, treg: FakeTreg | None = None) -> ChampionTools:
    return ChampionTools(
        read_site=pages_read,
        read_customers=pages_read,
        brain=scout or FakeScout(),
        linkedin=LinkedIn(treg or market()),
    )
