"""The database tables.

Each record keeps the fields the app reads and filters on as real columns, with constraints. The long tail of research
(scores, reasons, sources, job lookups) lives in one typed JSON column per table, so new research fields need no
migration, and nothing the research writes is lost.

Ids are short strings: rows that came over from the first version of the tracker keep their ids (c315, p750, a1007),
and new rows get a prefix and a random suffix.
"""

import enum
import secrets
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSONType = JSON().with_variant(JSONB(), "postgresql")

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def new_id(prefix: str) -> str:
    return f"{prefix}{secrets.token_hex(5)}"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def _enum(cls: type[enum.StrEnum]) -> Enum:
    return Enum(
        cls, native_enum=False, length=24, values_callable=lambda e: [m.value for m in e], validate_strings=True
    )


class Stage(enum.StrEnum):
    NOT_STARTED = "not_started"
    RESEARCHING = "researching"
    CONTACTED = "contacted"
    REPLIED = "replied"
    CALL_BOOKED = "call_booked"
    INTERVIEWING = "interviewing"
    TAKE_HOME = "take_home"
    OFFER = "offer"
    REJECTED = "rejected"
    PARKED = "parked"
    BENCH = "bench"


class MoveType(enum.StrEnum):
    REACH = "reach"  # one person's whole outreach, step by step (connect, email, bump, DM)
    APPLY = "apply"
    EMAIL = "email"
    CONNECT = "connect"
    COMMENT = "comment"
    POST = "post"
    BUMP = "bump"
    LINKEDIN_DM = "linkedin_dm"
    BUILD = "build"
    PREP = "prep"
    REVIEW = "review"


class MoveStatus(enum.StrEnum):
    OPEN = "open"
    DONE = "done"
    SKIPPED = "skipped"


class PersonStatus(enum.StrEnum):
    NONE = "none"
    REQUESTED = "requested"
    CONNECTED = "connected"
    REPLIED = "replied"
    NO_RESPONSE = "no_response"
    DECLINED = "declined"


class RoleInHire(enum.StrEnum):
    HIRING_MANAGER = "hiring manager"
    APPROVER = "approver"
    MANAGERS_BOSS = "manager's boss"
    BOSS = "boss"
    BOTH = "both"
    FOUNDER = "founder"
    RECRUITER = "recruiter"
    POSTER = "poster"
    PEER = "peer or stakeholder"


class Sureness(enum.StrEnum):
    CONFIRMED = "confirmed"
    LIKELY = "likely"
    GUESS = "guess"


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Company(Timestamps, Base):
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("c"))
    name: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str | None] = mapped_column(String(253), index=True)
    website: Mapped[str | None] = mapped_column(String(500))
    linkedin: Mapped[str | None] = mapped_column(String(500))
    hq: Mapped[str | None] = mapped_column(String(300))
    region: Mapped[str | None] = mapped_column(String(20))
    employees: Mapped[str | None] = mapped_column(String(200))
    stage: Mapped[Stage] = mapped_column(_enum(Stage), default=Stage.NOT_STARTED, index=True)
    wave: Mapped[str | None] = mapped_column(String(16))
    rank: Mapped[int | None] = mapped_column(Integer)
    score: Mapped[float | None] = mapped_column(Float)
    open_role: Mapped[str | None] = mapped_column(String(300))
    job_url: Mapped[str | None] = mapped_column(String(1000))
    posted: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str] = mapped_column(Text, default="")
    research: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)

    people: Mapped[list["Person"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    moves: Mapped[list["Move"]] = relationship(back_populates="company", cascade="all, delete-orphan")


class Person(Timestamps, Base):
    __tablename__ = "people"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("p"))
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(300), default="")
    linkedin: Mapped[str | None] = mapped_column(String(500))
    location: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str | None] = mapped_column(String(320))
    status: Mapped[PersonStatus] = mapped_column(_enum(PersonStatus), default=PersonStatus.NONE)
    role_in_hire: Mapped[RoleInHire] = mapped_column(_enum(RoleInHire), default=RoleInHire.HIRING_MANAGER)
    sureness: Mapped[Sureness | None] = mapped_column(_enum(Sureness))
    why: Mapped[str] = mapped_column(Text, default="")  # where the facts about their part in the hire came from
    left: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    drafts: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    details: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)  # angles, authority, motive, proof

    company: Mapped[Company] = relationship(back_populates="people")


class Move(Timestamps, Base):
    """One thing to do on a day: apply, a reach-out sequence to one person, a comment, a build."""

    __tablename__ = "moves"
    __table_args__ = (Index("ix_moves_status_due", "status", "due"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("a"))
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[str | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"), index=True)
    type: Mapped[MoveType] = mapped_column(_enum(MoveType))
    title: Mapped[str] = mapped_column(String(500))
    due: Mapped[date] = mapped_column(Date)
    status: Mapped[MoveStatus] = mapped_column(_enum(MoveStatus), default=MoveStatus.OPEN)
    notes: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str | None] = mapped_column(String(1000))
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # a reach sequence's state: its day 0, the dates of the steps done so far, the next step, why it closed
    sequence: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)

    company: Mapped[Company | None] = relationship(back_populates="moves")
    person: Mapped[Person | None] = relationship()


class Activity(Base):
    """The history: what happened and when, newest last."""

    __tablename__ = "activity"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    kind: Mapped[str] = mapped_column(String(24))
    text: Mapped[str] = mapped_column(Text)
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), index=True)
    person_id: Mapped[str | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"))
    move_id: Mapped[str | None] = mapped_column(ForeignKey("moves.id", ondelete="SET NULL"))


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONType)


class RadarItem(Timestamps, Base):
    """A role the radar found that isn't in the tracker yet, waiting to be added or dismissed."""

    __tablename__ = "radar_items"
    __table_args__ = (CheckConstraint("state IN ('new', 'added', 'dismissed')", name="state"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    company: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(1000))
    posted: Mapped[date | None] = mapped_column(Date)
    fit: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(12), default="new", index=True)
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"))
    data: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)


class Prospect(Timestamps, Base):
    """A funded startup to pitch for fractional GTM engineering: the research, plus what Sunny did about it."""

    __tablename__ = "prospects"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    rank: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str | None] = mapped_column(String(253), index=True)
    fit: Mapped[str] = mapped_column(String(12))
    research: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    mine: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)  # ticks, notes, drafts: never overwritten


class Magnet(Timestamps, Base):
    """A lead magnet built for one company: a list of people worth contacting, with why."""

    __tablename__ = "magnets"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("m"))
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(300), default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)


class LoginSession(Base):
    __tablename__ = "login_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    csrf: Mapped[str] = mapped_column(String(64))


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    ok: Mapped[bool] = mapped_column(Boolean)
