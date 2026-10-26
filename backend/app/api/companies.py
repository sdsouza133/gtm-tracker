"""Companies: the board, one company with everyone around the hire, adding and changing them."""

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api import patching
from app.auth import DbSession, SignedIn
from app.clock import Today
from app.models import Activity, Company, Move, MoveStatus, Person, Stage
from app.schemas import (
    ActivityOut,
    CompanyCreate,
    CompanyDetail,
    CompanyPatch,
    CompanySummary,
    MoveOut,
    Page,
    PersonOut,
    Promote,
)
from app.services.history import record
from app.services.outreach import promote
from app.services.stages import set_stage
from app.services.today import SURE_RANK

router = APIRouter(prefix="/api/companies", tags=["companies"], dependencies=[SignedIn])

COMPANY_ACTIVITY = 100
WARMTH = {"replied": 0, "connected": 1, "requested": 2, "none": 3, "no_response": 4, "declined": 5}


def get_company(session: Session, company_id: str) -> Company:
    company = session.get(Company, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That company isn't in the tracker.")
    return company


def _summaries(session: Session, companies: list[Company]) -> list[CompanySummary]:
    ids = [c.id for c in companies]
    people = dict(
        session.execute(
            select(Person.company_id, func.count()).where(Person.company_id.in_(ids)).group_by(Person.company_id)
        ).all()
    )
    # each company's next open move: the earliest due
    ranked = (
        select(Move, func.row_number().over(partition_by=Move.company_id, order_by=(Move.due, Move.id)).label("n"))
        .where(Move.company_id.in_(ids), Move.status == MoveStatus.OPEN)
        .subquery()
    )
    next_moves = {
        m.company_id: m
        for m in session.scalars(select(Move).join(ranked, Move.id == ranked.c.id).where(ranked.c.n == 1))
    }
    out = []
    for c in companies:
        summary = CompanySummary.model_validate(c)
        summary.people_count = people.get(c.id, 0)
        nxt = next_moves.get(c.id)
        summary.next_move = MoveOut.model_validate(nxt) if nxt else None
        out.append(summary)
    return out


def _filtered(query: Select[Any], stage: list[Stage] | None, q: str | None) -> Select[Any]:
    if stage:
        query = query.where(Company.stage.in_(stage))
    if q:
        like = f"%{q.strip().replace('%', r'\%').replace('_', r'\_')}%"
        query = query.where(or_(Company.name.ilike(like), Company.domain.ilike(like), Company.open_role.ilike(like)))
    return query


@router.get("")
def list_companies(
    session: DbSession,
    stage: Annotated[list[Stage] | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[CompanySummary]:
    """The board. Best-ranked first; filter by stage or search the name, domain and role."""
    total = session.scalar(_filtered(select(func.count()).select_from(Company), stage, q)) or 0
    rows = session.scalars(
        _filtered(select(Company), stage, q)
        .order_by(Company.rank.asc().nulls_last(), Company.score.desc().nulls_last(), Company.name)
        .limit(limit)
        .offset(offset)
    ).all()
    return Page(items=_summaries(session, list(rows)), total=total)


def _detail(session: Session, company: Company) -> CompanyDetail:
    company = session.scalars(
        select(Company)
        .where(Company.id == company.id)
        .options(selectinload(Company.people), selectinload(Company.moves))
        .execution_options(populate_existing=True)
    ).one()
    summary = _summaries(session, [company])[0]
    people = sorted(
        company.people,
        key=lambda p: (p.left, WARMTH.get(p.status.value, 9), SURE_RANK[p.sureness], p.name),
    )
    moves = sorted(company.moves, key=lambda m: (m.status is not MoveStatus.OPEN, m.due, m.id))
    activity = session.scalars(
        select(Activity).where(Activity.company_id == company.id).order_by(Activity.id.desc()).limit(COMPANY_ACTIVITY)
    ).all()
    return CompanyDetail(
        **summary.model_dump(),
        website=company.website,
        linkedin=company.linkedin,
        notes=company.notes,
        research=company.research,
        people=[PersonOut.model_validate(p) for p in people],
        moves=[MoveOut.model_validate(m) for m in moves],
        activity=[ActivityOut.model_validate(a) for a in activity],
    )


@router.get("/{company_id}")
def get_one(company_id: str, session: DbSession) -> CompanyDetail:
    """One company: the role, everyone around the hire (warmest first), its moves and its history."""
    return _detail(session, get_company(session, company_id))


@router.post("", status_code=status.HTTP_201_CREATED)
def create(body: CompanyCreate, session: DbSession) -> CompanyDetail:
    taken = f"A company at {body.domain} is already in the tracker."
    if body.domain and session.scalar(select(Company.id).where(func.lower(Company.domain) == body.domain.lower())):
        raise HTTPException(status.HTTP_409_CONFLICT, taken)
    company = Company(**body.model_dump())
    session.add(company)
    try:
        session.flush()
    except IntegrityError:  # the same domain added at the same moment (a double click)
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, taken) from None
    record(session, "system", f"{company.name}: added to the tracker", company_id=company.id)
    session.commit()
    return _detail(session, company)


@router.patch("/{company_id}")
def update(company_id: str, body: CompanyPatch, session: DbSession) -> CompanyDetail:
    company = get_company(session, company_id)
    fields = body.model_dump(exclude_unset=True)
    if (stage := fields.pop("stage", None)) is not None:
        set_stage(session, company, Stage(stage))
    if "research" in fields:
        research = dict(company.research)
        for key, value in (fields.pop("research") or {}).items():
            if value is None:
                research.pop(key, None)
            else:
                research[key] = value
        company.research = research
    if (wave := fields.get("wave")) is not None and wave != company.wave:
        record(session, "wave", f"{company.name}: moved to wave {wave}", company_id=company.id)
    patching.apply(company, fields)
    session.commit()
    return _detail(session, company)


@router.post("/{company_id}/promote")
def promote_company(company_id: str, body: Promote, session: DbSession, today: Today) -> CompanyDetail:
    """Off the bench and into the campaign."""
    company = get_company(session, company_id)
    promote(session, company, body.wave, today)
    session.commit()
    return _detail(session, company)
