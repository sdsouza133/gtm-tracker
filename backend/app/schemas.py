"""What the API takes and returns. Every field is typed and bounded; nothing is merged in unchecked."""

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    HttpUrl,
    TypeAdapter,
    field_validator,
)

from app.models import MoveStatus, MoveType, ParkedWhy, PersonStatus, RoleInHire, Stage, Sureness
from app.services.reach import Step

EMAIL_PATTERN = r"^[^@\s<>]+@[^@\s<>]+\.[A-Za-z]{2,}$"


_HTTP_URL = TypeAdapter(HttpUrl)
MAX_LINK = 1000


def _url(value: str) -> str:
    _HTTP_URL.validate_python(value)  # raises on anything that isn't an http(s) URL; the text is kept as given
    return value


def _clean(value: str) -> str:
    return " ".join(value.split())


def _link(value: object) -> str | None:
    """Research links are best effort: anything that isn't an http(s) URL ("Not found", javascript:...) is dropped
    rather than failing the whole daily batch."""
    if not isinstance(value, str) or not (text := value.strip()) or len(text) > MAX_LINK:
        return None
    try:
        return _url(text)
    except ValueError:
        return None


Url = Annotated[str, Field(min_length=1, max_length=1000), AfterValidator(_url)]
Link = Annotated[str | None, BeforeValidator(_link)]
Name = Annotated[str, Field(min_length=1, max_length=200), AfterValidator(_clean)]
Email = Annotated[str, Field(max_length=320, pattern=EMAIL_PATTERN), AfterValidator(str.lower)]
Notes = Annotated[str, Field(max_length=20_000)]


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page[T](BaseModel):
    items: list[T]
    total: int


# ----------------------------------------------------------------------------- people


class Draft(BaseModel):
    type: str
    subject: str = ""
    body: str


class PersonBrief(Out):
    id: str
    name: str
    title: str
    linkedin: str | None
    email: str | None
    location: str
    status: PersonStatus
    role_in_hire: RoleInHire
    sureness: Sureness | None
    left: bool


class PersonOut(PersonBrief):
    company_id: str
    why: str
    notes: str
    emailed_at: date | None
    ab_variant: str | None
    drafts: list[Draft]
    details: dict[str, Any]


class PersonCreate(BaseModel):
    company_id: str = Field(max_length=40)
    name: Name
    title: str = Field(default="", max_length=300)
    linkedin: Url | None = None
    location: str = Field(default="", max_length=200)
    email: Email | None = None
    role_in_hire: RoleInHire = RoleInHire.HIRING_MANAGER
    sureness: Sureness | None = None
    why: Notes = ""


class PersonPatch(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    linkedin: Url | None = None
    location: str | None = Field(default=None, max_length=200)
    email: Email | None = None
    status: PersonStatus | None = None
    role_in_hire: RoleInHire | None = None
    sureness: Sureness | None = None
    why: Notes | None = None
    notes: Notes | None = None
    left: bool | None = None
    ab_variant: Literal["A", "B"] | None = None
    loom: Literal["asked", "sent"] | None = Field(default=None, description="They asked for a Loom video; it's sent")


class Reply(BaseModel):
    text: str = Field(default="", max_length=2000)


# ----------------------------------------------------------------------------- moves


class Sequence(BaseModel):
    day0: date | None = None
    steps: dict[Step, str] = Field(default_factory=dict)
    next: str | None = None
    snooze: date | None = None
    closed: date | None = None
    replied: date | None = None


class CompanyBrief(Out):
    id: str
    name: str
    domain: str | None
    stage: Stage
    score: float | None
    open_role: str | None
    job_url: str | None
    posted: date | None
    region: str | None
    cant_apply: bool


class MoveOut(Out):
    id: str
    company_id: str | None
    person_id: str | None
    type: MoveType
    title: str
    due: date
    status: MoveStatus
    notes: str
    url: str | None
    skip_reason: str | None
    done_at: datetime | None
    sequence: Sequence | None = None  # only on a reach-out

    @field_validator("sequence", mode="before")
    @classmethod
    def _only_reach(cls, value: Any) -> Any:
        return value or None


class MoveCard(MoveOut):
    """A move with what it takes to do it right there: the company and the person, drafts included."""

    company: CompanyBrief | None
    person: PersonOut | None


class MoveCreate(BaseModel):
    type: MoveType = MoveType.CUSTOM
    title: str = Field(min_length=1, max_length=500)
    due: date | None = None
    company_id: str | None = Field(default=None, max_length=40)
    person_id: str | None = Field(default=None, max_length=40)
    notes: Notes = ""
    url: Url | None = None


class MovePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    notes: Notes | None = None
    url: Url | None = None
    due: date | None = None
    status: MoveStatus | None = None
    skip_reason: str | None = Field(default=None, max_length=200)


class StepTick(BaseModel):
    step: Step
    # "today", a day, "na" (can't: no email, not on LinkedIn), or null to untick
    value: Literal["today", "na"] | date | None = "today"


class Pull(BaseModel):
    n: int = Field(default=3, ge=1, le=20)


class Pulled(BaseModel):
    pulled: list[MoveOut]


class Cleared(BaseModel):
    cleared: int


class EnrichOut(BaseModel):
    tried: int = Field(description="People looked up with Apollo this time")
    found: int = Field(description="Of them, how many now have a work email")
    companies: int


# ----------------------------------------------------------------------------- companies


class CompanySummary(CompanyBrief):
    wave: str | None
    rank: int | None
    score: float | None
    hq: str | None
    employees: str | None
    parked_why: ParkedWhy | None
    parked_reason: str | None
    people_count: int = 0
    next_move: MoveOut | None = None


class ActivityOut(Out):
    id: int
    at: datetime
    kind: str
    text: str
    company_id: str | None
    person_id: str | None
    move_id: str | None
    xp: int


class CompanyDetail(CompanySummary):
    website: str | None
    linkedin: str | None
    notes: str
    research: dict[str, Any]
    people: list[PersonOut]
    moves: list[MoveOut]
    activity: list[ActivityOut]


class CompanyCreate(BaseModel):
    name: Name
    domain: str | None = Field(default=None, max_length=253)
    website: Url | None = None
    linkedin: Url | None = None
    hq: str | None = Field(default=None, max_length=300)
    region: str | None = Field(default=None, max_length=20)
    employees: str | None = Field(default=None, max_length=200)
    stage: Stage = Stage.NOT_STARTED
    wave: str | None = Field(default=None, max_length=16)
    open_role: str | None = Field(default=None, max_length=300)
    job_url: Url | None = None
    posted: date | None = None
    research: dict[str, Any] = Field(default_factory=dict)


class CompanyPatch(BaseModel):
    name: Name | None = None
    stage: Stage | None = None
    wave: str | None = Field(default=None, max_length=16)
    rank: int | None = None
    notes: Notes | None = None
    open_role: str | None = Field(default=None, max_length=300)
    job_url: Url | None = None
    posted: date | None = None
    cant_apply: bool | None = None
    # research keys to set (null removes one); what's not named stays
    research: dict[str, Any] | None = None


class Promote(BaseModel):
    wave: str = Field(default="2", min_length=1, max_length=16)


# ----------------------------------------------------------------------------- today and stats


class TodayGroup(BaseModel):
    key: str
    label: str
    moves: list[MoveCard]


class LoomAsk(Out):
    """Someone who asked for a Loom video, and where they work."""

    person: PersonOut
    company: CompanyBrief | None


class TodayOut(BaseModel):
    today: date
    groups: list[TodayGroup]
    overdue: int
    more: int = Field(description="Companies held back for another day by the daily limit")
    done_today: list[MoveCard]
    waiting: list[MoveCard]
    waiting_total: int
    looms: list[LoomAsk]


class DayCount(BaseModel):
    day: date
    moves: int


class StatsOut(BaseModel):
    xp: int
    level: int
    level_title: str
    level_floor_xp: int
    next_level_xp: int
    streak: int
    best_streak: int
    streak_min: int
    today_moves: int
    recent: list[DayCount]
    funnel: dict[str, int]
    in_play: int
    days_left: int | None


class PlanDay(BaseModel):
    day: date
    moves: list[MoveCard]


class NoteCreate(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    company_id: str | None = Field(default=None, max_length=40)
    person_id: str | None = Field(default=None, max_length=40)


# ----------------------------------------------------------------------------- settings


class DayBlocks(BaseModel):
    outreach: bool = False
    content: bool = False
    course: bool = False


class Snippets(BaseModel):
    location_answer: str = Field(default="", max_length=5000)
    dm_on_accept: str = Field(default="", max_length=5000)
    bump_template: str = Field(default="", max_length=5000)


class SettingsOut(BaseModel):
    """The settings the app uses. Only these can be written."""

    model_config = ConfigDict(extra="forbid")

    candidate: str | None = Field(default=None, max_length=200)
    pay_ask: str | None = Field(default=None, max_length=200)
    campaign_start: date | None = None
    deadline: date | None = None
    loom_url: Url | None = None
    snippets: Snippets | None = None
    days: dict[date, DayBlocks] | None = None
    fx_goals: dict[str, Annotated[int, Field(ge=0, le=30)]] | None = None  # "default" and per-day overrides

    @field_validator("fx_goals")
    @classmethod
    def _goal_keys(cls, value: dict[str, int] | None) -> dict[str, int] | None:
        for key in value or {}:
            if key != "default" and date.fromisoformat(key).isoformat() != key:
                raise ValueError("Goal keys are 'default' or a day as YYYY-MM-DD.")
        return value


# ----------------------------------------------------------------------------- fractional


class ProspectPerson(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    title: str = Field(default="", max_length=1000)
    linkedin: Link = None
    location: str = Field(default="", max_length=1000)
    since: str = Field(default="", max_length=1000)


class ProspectIn(BaseModel):
    """One prospect from the daily research. Replaces the research on every sync; never touches what you did."""

    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    day: date
    rank: int = Field(ge=1, le=1000)
    name: Name
    domain: str | None = Field(default=None, max_length=253)
    website: Link = None
    linkedin: Link = None
    hq: str = Field(default="", max_length=1000)
    employees: str = Field(default="", max_length=1000)
    stage: str = Field(default="", max_length=1000)  # funding stage: Seed, Series A
    round: str = Field(default="", max_length=1000)
    raised_total: str = Field(default="", max_length=1000)
    investors: str = Field(default="", max_length=1000)
    dmarc: str = Field(default="", max_length=1000)
    spf: str = Field(default="", max_length=1000)
    fit: str = Field(default="good", max_length=12)
    fit_reason: str = Field(default="", max_length=5000)
    offer: str = Field(default="", max_length=5000)
    pvp: str = Field(default="", max_length=5000)  # the free first thing to build for them
    why_now: str = Field(default="", max_length=5000)
    research: dict[str, Any] = Field(default_factory=dict)
    people: list[ProspectPerson] = Field(default_factory=list, max_length=20)


class ProspectSync(BaseModel):
    prospects: list[ProspectIn] = Field(max_length=500)

    @field_validator("prospects")
    @classmethod
    def _unique_ids(cls, value: list[ProspectIn]) -> list[ProspectIn]:
        ids = [p.id for p in value]
        if len(ids) != len(set(ids)):
            raise ValueError("Each prospect id may appear only once.")
        return value


class Synced(BaseModel):
    added: int
    updated: int


class FollowUpOut(BaseModel):
    step: str
    due: date


class ProspectCard(BaseModel):
    id: str
    day: date
    effective_day: date
    rank: int
    name: str
    domain: str | None
    website: str | None
    round: str
    hq: str
    employees: str
    dmarc: str
    one_liner: str
    why_now: str
    people: list[ProspectPerson]
    touched: list[str]  # keys of the people reached
    status: str
    stage: str
    next_step: str
    follow_up: FollowUpOut | None
    first_touch: date | None
    xp: int


class ProspectDetail(ProspectCard):
    linkedin: str | None
    spf: str
    fit: str
    fit_reason: str
    offer: str
    pvp: str
    research: dict[str, Any]
    touches: dict[str, dict[str, str]]
    steps: dict[str, str]
    lost_reason: str
    my_notes: str
    draft: str
    day_override: date | None


class TouchChange(BaseModel):
    person: str = Field(max_length=80)
    kind: Literal["connect", "dm", "email"]
    on: bool = True


class StepChange(BaseModel):
    name: Literal["researched", "fu1", "fu2", "replied", "call", "proposal", "won"]
    on: bool = True


class ProspectPatch(BaseModel):
    touch: TouchChange | None = None
    step: StepChange | None = None
    status: Literal["open", "won", "lost", "skipped"] | None = None
    lost_reason: str | None = Field(default=None, max_length=20_000)
    my_notes: str | None = Field(default=None, max_length=20_000)
    draft: str | None = Field(default=None, max_length=20_000)
    day_override: date | None = None
    when: date | None = None  # back-date a tick (never in the future); today by default


class LevelOut(BaseModel):
    number: int
    name: str
    floor_xp: int
    next_xp: int | None
    next_name: str | None


class BadgeOut(BaseModel):
    key: str
    name: str
    description: str
    earned: bool


class HeatDay(BaseModel):
    day: date
    hits: int
    goal: int


class FxStats(BaseModel):
    xp: int
    level: LevelOut
    streak: int
    best_streak: int
    heat: list[HeatDay]
    clients: int
    monthly_revenue: int
    revenue_goal: int
    funnel: dict[str, int]
    badges: list[BadgeOut]


class FxBoard(BaseModel):
    today: date
    goal: int
    hits_today: int
    follow_ups_due: list[ProspectCard]
    follow_ups_due_total: int
    follow_ups_later: int
    carried_over: list[ProspectCard]
    carried_over_total: int
    todays_list: list[ProspectCard]
    reached_today: list[ProspectCard]
    coming_up: list[ProspectCard]
    coming_up_total: int
    stats: FxStats


class FxColumn(BaseModel):
    key: str
    label: str
    total: int
    items: list[ProspectCard]


# ----------------------------------------------------------------------------- radar


class RadarConfigPatch(BaseModel):
    """Change what the radar looks for; anything not named keeps its value."""

    keywords: list[Annotated[str, Field(min_length=1, max_length=100)]] | None = Field(default=None, max_length=20)
    locations: list[Annotated[str, Field(min_length=1, max_length=100)]] | None = Field(default=None, max_length=10)
    per_search: int | None = Field(default=None, ge=1, le=100)
    daily_usd: float | None = Field(default=None, ge=0, le=5)
    hour: int | None = Field(default=None, ge=0, le=23)
    min_fit: int | None = Field(default=None, ge=1, le=3)
    recent_days: int | None = Field(default=None, ge=1, le=60)
    ats_search: bool | None = None
    post_search: bool | None = None
    core_only: bool | None = None
    toronto_ok: bool | None = None
    min_usd: int | None = Field(default=None, ge=0, le=1_000_000)
    min_cad: int | None = Field(default=None, ge=0, le=1_000_000)


class RadarConfigOut(BaseModel):
    keywords: list[str]
    locations: list[str]
    per_search: int
    daily_usd: float
    hour: int
    min_fit: int
    recent_days: int
    ats_search: bool
    post_search: bool
    core_only: bool
    toronto_ok: bool
    min_usd: int
    min_cad: int


class RadarItemOut(BaseModel):
    id: str
    company: str
    title: str
    url: str
    posted: date | None
    fit: int
    state: str
    company_id: str | None
    location: str
    salary: str
    flags: list[str]
    source: str
    snippet: str
    on_bench: bool


class HiringPost(BaseModel):
    id: str
    url: str
    posted: str
    author: str
    author_url: str
    headline: str
    recruiter: bool
    text: str


class RadarOut(BaseModel):
    status: dict[str, Any]
    config: RadarConfigOut
    items: list[RadarItemOut]
    posts: list[HiringPost]
    apify: bool


class RadarAdded(BaseModel):
    company_id: str
    move_id: str
