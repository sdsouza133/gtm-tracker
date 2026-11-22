"""The champion checks against a frozen set of made-up people, each with the answer the rules must give.

Like a golden set: loosen a rule (drop "intern", allow a fourth month, read the wrong field) and a case here fails.
Every reason the rules can give has at least one case."""

from datetime import date

import pytest

from app.magnet import traps
from app.magnet.linkedin import History, Job, Mover

TODAY = date(2026, 11, 22)
RULES = traps.Rules(
    vendor="cxhero",
    competitors=frozenset({"rivalcx"}),
    customers=frozenset({"glowco", "shoebird"}),
    customer_pages=frozenset({"glowco", "shoebird"}),
    regions=frozenset({"US", "CA"}),
    keywords=("Customer Experience", "Support"),
)


def now(title: str, company: str = "Newbrand", months: int = 1, industry: str = "Retail", page: str = "") -> Job:
    return Job(title=title, company=company, company_linkedin=page, industry=industry, months=months)


def someone(*jobs: Job, key: str = "k1", location: str = "Austin, Texas, United States", hidden: bool = False) -> Mover:
    return Mover(
        key=key,
        url=f"https://www.linkedin.com/in/{key}",
        name="Pat Example",
        location=location,
        jobs=jobs,
        hidden=hidden,
    )


GOLDEN: list[tuple[str, Mover, str | None]] = [
    ("a clean move", someone(now("VP Customer Experience")), None),
    ("hidden by LinkedIn", someone(now("VP CX"), hidden=True), "hidden"),
    ("listed twice", someone(now("VP CX"), key="seen-before"), "duplicate"),
    ("no current job", someone(), "no_current_role"),
    ("only an advisor now", someone(now("Advisor", "Someco")), "side_role"),
    ("board seat and freelance only", someone(now("Board Member"), now("Freelance consultant")), "side_role"),
    ("self-employed", someone(now("CX consulting", "Self-employed")), "side_role"),
    ("advisor plus a real job: the real one counts", someone(now("Advisor", "Someco"), now("VP CX")), None),
    ("joined the vendor", someone(now("Head of Partnerships", "CXHero Inc.")), "joined_vendor"),
    ("joined a competitor", someone(now("Head of CX", "Rival CX")), "joined_competitor"),
    ("moved to another customer, by name", someone(now("Head of CX", "Glowco")), "joined_customer"),
    (
        "moved to another customer, by page",
        someone(now("Head of CX", "GC", page="https://www.linkedin.com/company/glowco")),
        "joined_customer",
    ),
    ("intern", someone(now("Customer Experience Intern")), "junior"),
    ("coordinator", someone(now("CX Coordinator")), "junior"),
    ("CX associate", someone(now("CX Associate")), "junior"),
    ("associate director is senior", someone(now("Associate Director, Customer Experience")), None),
    ("assistant", someone(now("Assistant to the CEO")), "junior"),
    ("assistant vice president is senior", someone(now("Assistant Vice President, Support")), None),
    ("3 months in is still fresh", someone(now("Head of CX", months=3)), None),
    ("4 months in is old news", someone(now("Head of CX", months=4)), "stale_move"),
    ("junior and stale: the first check wins", someone(now("CX Intern", months=8)), "junior"),
    ("in the UK", someone(now("Head of CX"), location="London, England, United Kingdom"), "outside_region"),
    ("in Canada", someone(now("Head of CX"), location="Toronto, Ontario, Canada"), None),
    (
        "location that names no country passes",
        someone(now("Head of CX"), location="Los Angeles Metropolitan Area"),
        None,
    ),
    ("a US state, no country", someone(now("Head of CX"), location="Greater Boston, Massachusetts"), None),
    (
        "joined a VC firm",
        someone(now("Partner", "Acorn", industry="Venture Capital and Private Equity Principals")),
        "non_buyer_industry",
    ),
    (
        "joined a staffing firm",
        someone(now("Account Director", "Hirefast", industry="Staffing and Recruiting")),
        "non_buyer_industry",
    ),
]


@pytest.mark.parametrize(("case", "mover", "reason"), GOLDEN, ids=[c for c, _, _ in GOLDEN])
def test_each_person_gets_the_answer_written_down(case: str, mover: Mover, reason: str | None) -> None:
    assert traps.judge(mover, RULES, seen={"seen-before"}) == reason


def test_a_vendor_selling_to_investors_keeps_them() -> None:
    to_vcs = traps.Rules(**{**RULES.__dict__, "sells_to_non_buyers": True})
    vc = someone(now("Partner", "Acorn", industry="Venture Capital and Private Equity Principals"))
    assert traps.judge(vc, to_vcs, seen=set()) is None


def test_no_region_check_when_the_icp_sells_anywhere() -> None:
    assert traps.allowed_regions(["Global"]) == frozenset()
    assert traps.allowed_regions(["United States", "Canada"]) == {"US", "CA"}
    assert traps.allowed_regions(["North America"]) == {"US", "CA", "MX"}
    assert traps.allowed_regions(["Mid-market"]) == frozenset()  # names no place: no check
    anywhere = traps.Rules(**{**RULES.__dict__, "regions": frozenset()})
    assert traps.judge(someone(now("Head of CX"), location="London, England, United Kingdom"), anywhere, set()) is None


def test_a_country_named_on_its_own_counts_as_a_region() -> None:
    assert traps.allowed_regions(["Germany"]) == {"DE"}
    assert traps.allowed_regions(["United States", "Germany"]) == {"US", "DE"}
    assert traps.allowed_regions(["DACH: Germany, Austria and Switzerland"]) == {"DE", "AT", "CH"}
    us_and_germany = traps.Rules(**{**RULES.__dict__, "regions": frozenset({"US", "DE"})})
    assert traps.judge(someone(now("Head of CX"), location="Berlin, Germany"), us_and_germany, set()) is None


def job(title: str, company: str, page: str, start: date, end: date | None) -> Job:
    months = ((end or TODAY).year - start.year) * 12 + (end or TODAY).month - start.month
    return Job(title=title, company=company, company_linkedin=page, industry="", months=months, start=start, end=end)


GLOWCO = "https://www.linkedin.com/company/glowco"
MOVED = someone(now("VP Customer Experience", "Newbrand", months=2, industry="Retail"))
VERIFY: list[tuple[str, History | None, str | None]] = [
    (
        "worked at a customer, left, and just moved",
        History(
            "",
            (
                job("VP CX", "Newbrand", "", date(2026, 9, 1), None),
                job("CX Manager", "Glowco", GLOWCO, date(2021, 1, 1), date(2026, 8, 1)),
            ),
        ),
        None,
    ),
    ("no history", None, "no_history"),
    ("empty history", History("", ()), "no_history"),
    (
        "never at a customer",
        History(
            "",
            (
                job("VP CX", "Newbrand", "", date(2026, 9, 1), None),
                job("CX Manager", "Elsewhere", "", date(2020, 1, 1), date(2026, 8, 1)),
            ),
        ),
        "not_verified",
    ),
    (
        "an advisor seat at the customer doesn't count",
        History(
            "",
            (
                job("VP CX", "Newbrand", "", date(2026, 9, 1), None),
                job("Advisor", "Glowco", GLOWCO, date(2025, 1, 1), None),
            ),
        ),
        "not_verified",
    ),
    (
        "still holds the customer job",
        History(
            "",
            (
                job("VP CX", "Newbrand", "", date(2026, 9, 1), None),
                job("CX Lead", "Glowco", GLOWCO, date(2022, 1, 1), None),
            ),
        ),
        "still_at_customer",
    ),
    (
        "left the customer over 3 years before",
        History(
            "",
            (
                job("VP CX", "Newbrand", "", date(2026, 9, 1), None),
                job("CX Manager", "Glowco", GLOWCO, date(2016, 1, 1), date(2019, 6, 1)),
            ),
        ),
        "left_customer_long_ago",
    ),
    (
        "the history's current job isn't the one the search found",
        History(
            "",
            (
                job("Head of Partnerships", "CXHero", "", date(2026, 9, 1), None),
                job("CX Manager", "Glowco", GLOWCO, date(2021, 1, 1), date(2026, 8, 1)),
            ),
        ),
        "not_verified",
    ),
    (
        "back at a company they'd left before the customer",
        History(
            "",
            (
                job("VP CX", "Newbrand", "", date(2026, 10, 1), None),
                job("CX Manager", "Glowco", GLOWCO, date(2021, 1, 1), date(2026, 8, 1)),
                job("Support Rep", "Newbrand", "", date(2016, 1, 1), date(2020, 6, 1)),
            ),
        ),
        None,
    ),
    (
        "a new title where they've been since 2024",
        History(
            "",
            (
                job("VP CX", "Newbrand", "", date(2026, 9, 1), None),
                job("CX Manager", "Newbrand", "", date(2024, 2, 1), date(2026, 9, 1)),
                job("CX Lead", "Glowco", GLOWCO, date(2021, 1, 1), date(2024, 1, 1)),
            ),
        ),
        "internal_move",
    ),
]


@pytest.mark.parametrize(("case", "history", "reason"), VERIFY, ids=[c for c, _, _ in VERIFY])
def test_the_work_history_checks(case: str, history: History | None, reason: str | None) -> None:
    got, verified = traps.verify(MOVED, history, RULES, TODAY)
    assert got == reason
    assert (verified is None) == (reason is not None)


def test_the_new_job_matches_by_its_linkedin_page_when_the_names_differ() -> None:
    newbrand = "https://www.linkedin.com/company/newbrand"
    mover = someone(now("VP CX", "Newbrand", months=2, page=newbrand))
    history = History(
        "",
        (
            job("VP CX", "NB Labs", newbrand, date(2026, 9, 1), None),
            job("CX Manager", "Glowco", GLOWCO, date(2021, 1, 1), date(2026, 8, 1)),
        ),
    )
    reason, found = traps.verify(mover, history, RULES, TODAY)
    assert reason is None
    assert found is not None
    assert found.now.company == "NB Labs"


def test_a_run_at_a_company_goes_back_across_promotions_but_not_across_a_job_elsewhere() -> None:
    vp = job("VP CX", "Newbrand", "", date(2026, 9, 1), None)
    manager = job("CX Manager", "Newbrand", "", date(2024, 2, 1), date(2026, 9, 1))
    customer = job("CX Lead", "Glowco", GLOWCO, date(2021, 1, 1), date(2024, 1, 1))
    assert traps.stint_start((vp, manager, customer), vp) == date(2024, 2, 1)  # a promotion: the same run
    earlier = job("Support Rep", "Newbrand", "", date(2016, 1, 1), date(2020, 6, 1))
    assert traps.stint_start((vp, customer, earlier), vp) == date(2026, 9, 1)  # back after a customer: a new run
    advisor = job("Advisor", "Someco", "", date(2025, 1, 1), None)
    assert traps.stint_start((vp, advisor, manager), vp) == date(2024, 2, 1)  # a side role doesn't break it
    undated = Job(title="VP CX", company="Newbrand", company_linkedin="", industry="", months=0)
    assert traps.stint_start((undated,), undated) is None


def verified(title: str, start: date, end: date, gap: int) -> traps.Verified:
    return traps.Verified(was=job(title, "Glowco", GLOWCO, start, end), now=now("VP CX"), gap=gap)


def test_grades() -> None:
    long_cx = verified("Senior Manager, Customer Experience", date(2021, 1, 1), date(2026, 8, 1), gap=1)
    assert traps.grade(long_cx, is_named=True, keywords=RULES.keywords) == "A"  # named on the site
    assert traps.grade(long_cx, is_named=False, keywords=RULES.keywords) == "B"
    leader = verified("COO", date(2024, 1, 1), date(2026, 7, 1), gap=4)
    assert traps.grade(leader, is_named=False, keywords=RULES.keywords) == "B"  # a leader's title counts too
    short = verified("Customer Experience Associate", date(2024, 1, 1), date(2024, 6, 1), gap=2)
    assert traps.grade(short, is_named=False, keywords=RULES.keywords) == "C"  # five months: too short
    long_ago = verified("CX Manager", date(2021, 1, 1), date(2024, 1, 1), gap=33)
    assert traps.grade(long_ago, is_named=False, keywords=RULES.keywords) == "C"  # left over two years before
    other = verified("Warehouse Associate", date(2020, 1, 1), date(2026, 8, 1), gap=1)
    assert traps.grade(other, is_named=False, keywords=RULES.keywords) == "C"


def test_named_by_name_or_linkedin_address() -> None:
    mover = Mover("k", "https://www.linkedin.com/in/ACwAAexample", "Dana Named", "", (), hidden=False)
    assert traps.named(mover, None, [("Dana  Named", "")])
    public = History("https://www.linkedin.com/in/dana-n", ())
    assert traps.named(mover, public, [("D. Named", "dana-n")])
    assert not traps.named(mover, public, [("Someone Else", "someone-else")])


def test_country_of() -> None:
    assert traps.country_of("Atlanta, Georgia, United States") == "US"
    assert traps.country_of("New York City Metropolitan Area") == "US"
    assert traps.country_of("Greater Melbourne Area") == "AU"
    assert traps.country_of("Davao, Davao Region, Philippines") == "PH"
    assert traps.country_of("Netherlands") == "NL"
    assert traps.country_of("Los Angeles Metropolitan Area") == ""


def test_every_reason_has_a_case() -> None:
    covered = {reason for _, _, reason in GOLDEN} | {reason for _, _, reason in VERIFY}
    covered |= {"not_icp", "over_cap"}  # given by the build (Claude's screen, the lookup cap): test_magnet_champions
    assert set(traps.REASONS) <= covered
