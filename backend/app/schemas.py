"""What the API takes and returns. Every field is typed and bounded; nothing is merged in unchecked."""

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.models import MoveStatus, MoveType, ParkedWhy, PersonStatus, RoleInHire, Stage, Sureness
from app.services.reach import Step

EMAIL_PATTERN = r"^[^@\s<>]+@[^@\s<>]+\.[A-Za-z]{2,}$"


def _url(value: str) -> str:
    HttpUrl(value)  # raises on anything that isn't an http(s) URL
    return value


def _clean(value: str) -> str:
    return " ".join(value.split())


Url = Annotated[str, Field(min_length=1, max_length=1000), AfterValidator(_url)]
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


class TodayOut(BaseModel):
    today: date
    groups: list[TodayGroup]
    overdue: int
    done_today: list[MoveCard]
    waiting: list[MoveCard]
    waiting_total: int


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
