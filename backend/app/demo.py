"""Made-up demo data, for local development, screenshots and anyone trying the app. Every company and person here is
fictional; real data never lives in the repository."""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Company, Move, MoveType, Person, PersonStatus, RoleInHire, Setting, Stage, Sureness


@dataclass(frozen=True)
class DemoPerson:
    name: str
    title: str
    location: str
    role: RoleInHire
    sure: Sureness


@dataclass(frozen=True)
class DemoCompany:
    id: str
    name: str
    domain: str
    hq: str
    region: str
    employees: str
    stage: Stage
    open_role: str
    posted_days_ago: int
    research: dict[str, str]
    people: list[DemoPerson] = field(default_factory=list)


P = DemoPerson
COMPANIES = [
    DemoCompany(
        id="demo-northwind",
        name="Northwind Labs",
        domain="northwind.example",
        hq="Toronto, SF and Paris",
        region="Canada",
        employees="about 300",
        stage=Stage.CONTACTED,
        open_role="GTM Engineer, Growth",
        posted_days_ago=3,
        research={
            "salary": "CA$124–137K + equity",
            "where": "Toronto, hybrid",
            "one_liner": "AI agents for ecommerce support",
            "watch_out": "Pay tops out right at your floor. Ask about room above the band.",
        },
        people=[
            P("Priya Raman", "Senior GTM AI Program Manager", "Toronto", RoleInHire.PEER, Sureness.LIKELY),
            P("Jordan Kim", "GTM Engineer", "Toronto", RoleInHire.PEER, Sureness.CONFIRMED),
            P("Alex Moreau", "Senior Manager, GTM Ops", "Lisbon", RoleInHire.HIRING_MANAGER, Sureness.GUESS),
            P("Chris Douglas", "Director of Demand Generation", "Ontario", RoleInHire.PEER, Sureness.LIKELY),
            P("Morgan Ellis", "VP Marketing", "Boston", RoleInHire.MANAGERS_BOSS, Sureness.LIKELY),
            P("Taylor Reed", "Senior GTM Recruiter", "Canada", RoleInHire.RECRUITER, Sureness.LIKELY),
        ],
    ),
    DemoCompany(
        id="demo-brightline",
        name="Brightline AI",
        domain="brightline.example",
        hq="San Francisco",
        region="US",
        employees="about 900",
        stage=Stage.NOT_STARTED,
        open_role="Sr. Manager, GTM Engineering",
        posted_days_ago=3,
        research={"salary": "$150–181K", "where": "Remote US", "one_liner": "Intent data and ABM platform"},
        people=[
            P(
                "Dana Ortiz",
                "Senior Director, Marketing Operations",
                "Remote",
                RoleInHire.HIRING_MANAGER,
                Sureness.LIKELY,
            ),
            P("Tom Becker", "GTM Engineer", "Austin", RoleInHire.PEER, Sureness.LIKELY),
        ],
    ),
    DemoCompany(
        id="demo-ledgerloop",
        name="Ledgerloop",
        domain="ledgerloop.example",
        hq="New York",
        region="US",
        employees="11-50",
        stage=Stage.NOT_STARTED,
        open_role="GTM Engineer (first hire)",
        posted_days_ago=4,
        research={"salary": "$115–135K + bonus", "where": "Remote US or Canada", "one_liner": "Analytics for advisors"},
        people=[P("Marcus Lee", "Head of Sales", "New York", RoleInHire.HIRING_MANAGER, Sureness.LIKELY)],
    ),
    DemoCompany(
        id="demo-orbit",
        name="Orbit Health",
        domain="orbit.example",
        hq="Boston",
        region="US",
        employees="51-200",
        stage=Stage.REPLIED,
        open_role="GTM Systems Lead",
        posted_days_ago=12,
        research={"salary": "$140–160K", "where": "Remote US"},
        people=[P("Sam Whitaker", "VP Revenue Operations", "Boston", RoleInHire.HIRING_MANAGER, Sureness.CONFIRMED)],
    ),
]


def seed_demo(session: Session, today: date | None = None) -> str:
    """Adds the demo data to an empty database. Refuses to touch a database that already has companies."""
    if session.scalar(select(func.count()).select_from(Company)):
        return "The database already has companies; nothing added."
    today = today or datetime.now(get_settings().tz).date()
    for spec in COMPANIES:
        company = Company(
            id=spec.id,
            name=spec.name,
            domain=spec.domain,
            hq=spec.hq,
            region=spec.region,
            employees=spec.employees,
            stage=spec.stage,
            open_role=spec.open_role,
            posted=today - timedelta(days=spec.posted_days_ago),
            research=dict(spec.research),
        )
        session.add(company)
        session.add(Move(company=company, type=MoveType.APPLY, title=f"Apply: {spec.open_role}", due=today))
        for i, p in enumerate(spec.people):
            person = Person(
                id=f"{spec.id}-p{i}",
                company=company,
                name=p.name,
                title=p.title,
                location=p.location,
                role_in_hire=p.role,
                sureness=p.sure,
                status=PersonStatus.REQUESTED if p.role is RoleInHire.RECRUITER else PersonStatus.NONE,
            )
            session.add(person)
            day0 = today + timedelta(days=i % 3)
            session.add(
                Move(
                    company=company,
                    person=person,
                    type=MoveType.REACH,
                    title=f"Reach {p.name}",
                    due=day0,
                    sequence={"day0": day0.isoformat(), "steps": {}, "next": "request"},
                )
            )
    if session.get(Setting, "candidate") is None:  # keep a name that's already set
        session.add(Setting(key="candidate", value="Demo Candidate"))
    session.commit()
    return f"Added {len(COMPANIES)} demo companies."
