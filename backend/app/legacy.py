"""Bring data over from the first version of the tracker: its `/api/export` JSON, and optionally its `/api/fx` JSON
for Fractional progress (the old export left that out).

Ids are kept, so links between rows survive and the move can be checked row by row. Fields the new tables don't have
as columns go into each row's JSON (`research` for companies, `details` for people), so nothing is dropped.
"""

import re
from collections import Counter
from datetime import UTC, date, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Activity,
    Company,
    Magnet,
    Move,
    MoveStatus,
    MoveType,
    ParkedWhy,
    Person,
    PersonStatus,
    Prospect,
    RadarItem,
    RoleInHire,
    Setting,
    Stage,
    Sureness,
)
from app.schemas import ProspectIn
from app.services import fx_board
from app.services.outreach import REPLY_XP, refresh
from app.services.stages import STAGE_XP

COMPANY_COLUMNS = {
    "id",
    "name",
    "domain",
    "website",
    "company_linkedin",
    "hq",
    "region",
    "employees",
    "stage",
    "wave",
    "rank",
    "score",
    "open_role",
    "job_url",
    "posted",
    "notes",
    "parked_why",
    "parked_reason",
    "cant_apply",
}
PERSON_COLUMNS = {
    "id",
    "company_id",
    "name",
    "title",
    "linkedin",
    "location",
    "email",
    "status",
    "role_in_hire",
    "hm_confidence",
    "hm_why",
    "left",
    "notes",
    "drafts",
    "emailed_at",
    "ab_variant",
}
REACH_KEYS = ("day0", "steps", "next", "snooze", "closed", "replied")
SKIPPED_SETTINGS = {"migrations_done", "radar_status"}  # the old app's bookkeeping, meaningless here
STAGE_WORDS = {"call booked": Stage.CALL_BOOKED, "interviewing": Stage.INTERVIEWING, "take home": Stage.TAKE_HOME}
STAGE_WORDS["offer"] = Stage.OFFER
STAGE_AT_END = re.compile(r"(call booked|interviewing|take home|offer)\s*$", re.IGNORECASE)
FX_MINE = ("touches", "steps", "status", "lost_reason", "my_notes", "draft", "day_override", "added_at")


class ImportRefusedError(RuntimeError):
    """The database already has data; importing would mix two trackers."""


def _clip(value: Any, n: int) -> str | None:
    if value is None or value == "":
        return None
    return str(value)[:n]


def _day(value: Any) -> date | None:
    if isinstance(value, str) and len(value) >= 10:  # noqa: PLR2004  (YYYY-MM-DD)
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _at(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def _enum[E](cls: type[E], value: Any, default: E) -> E:
    try:
        return cls(value)  # type: ignore[call-arg]
    except ValueError:
        return default


def _rank(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def company(c: dict[str, Any]) -> Company:
    stage = _enum(Stage, c.get("stage"), Stage.NOT_STARTED)
    return Company(
        id=c["id"],
        name=_clip(c.get("name"), 200) or c["id"],
        domain=_clip((c.get("domain") or "").lower(), 253),
        website=_clip(c.get("website"), 500),
        linkedin=_clip(c.get("company_linkedin"), 500),
        hq=_clip(c.get("hq"), 300),
        region=_clip(c.get("region"), 20),
        employees=_clip(c.get("employees"), 200),
        stage=stage,
        wave=_clip(c.get("wave"), 16),
        rank=_rank(c.get("rank")),
        score=_float(c.get("score")),
        open_role=_clip(c.get("open_role"), 300),
        job_url=_clip(c.get("job_url"), 1000),
        posted=_day(c.get("posted")),
        notes=str(c.get("notes") or ""),
        parked_why=_enum(ParkedWhy, c.get("parked_why"), None) if stage is Stage.PARKED else None,
        parked_reason=c.get("parked_reason") if stage is Stage.PARKED else None,
        cant_apply=bool(c.get("cant_apply")),
        research={k: v for k, v in c.items() if k not in COMPANY_COLUMNS},
    )


def person(p: dict[str, Any]) -> Person:
    return Person(
        id=p["id"],
        company_id=p["company_id"],
        name=_clip(p.get("name"), 200) or p["id"],
        title=_clip(p.get("title"), 300) or "",
        linkedin=_clip(p.get("linkedin"), 500),
        location=_clip(p.get("location"), 200) or "",
        email=_clip((p.get("email") or "").strip().lower(), 320),
        status=_enum(PersonStatus, p.get("status"), PersonStatus.NONE),
        role_in_hire=_enum(RoleInHire, p.get("role_in_hire"), RoleInHire.HIRING_MANAGER),
        sureness=_enum(Sureness, p.get("hm_confidence"), None),
        why=str(p.get("hm_why") or ""),
        left=bool(p.get("left")),
        notes=str(p.get("notes") or ""),
        drafts=[d for d in p.get("drafts") or [] if isinstance(d, dict)],
        emailed_at=_day(p.get("emailed_at")),
        ab_variant=p.get("ab_variant") if p.get("ab_variant") in ("A", "B") else None,
        details={k: v for k, v in p.items() if k not in PERSON_COLUMNS},
    )


def move(a: dict[str, Any], people: set[str], companies: set[str]) -> Move:
    kind = _enum(MoveType, a.get("type"), MoveType.CUSTOM)
    due = _day(a.get("due")) or _day(a.get("day0")) or _day(a.get("created_at")) or date.today()  # noqa: DTZ011
    m = Move(
        id=a["id"],
        company_id=a.get("company_id") if a.get("company_id") in companies else None,
        person_id=a.get("contact_id") if a.get("contact_id") in people else None,
        type=kind,
        title=_clip(a.get("title"), 500) or kind.value,
        due=due,
        status=_enum(MoveStatus, a.get("status"), MoveStatus.OPEN),
        notes=str(a.get("notes") or ""),
        url=_clip(a.get("url"), 1000),
        skip_reason=_clip(a.get("skip_reason"), 200),
        done_at=_at(a.get("done_at")),
        created_at=_at(a.get("created_at")) or datetime.now(UTC),
        sequence={k: a[k] for k in REACH_KEYS if a.get(k)} if kind is MoveType.REACH else {},
    )
    if kind is MoveType.REACH:
        m.sequence.setdefault("day0", due.isoformat())
        m.sequence.setdefault("steps", {})
        refresh(m)  # status, due and next from the ticks, by the new rules
    return m


def activity(
    line: dict[str, Any], ids: dict[str, set[str]], won: set[tuple[str, str]], companies: dict[str, Company]
) -> Activity:
    company_id = line.get("company_id") if line.get("company_id") in ids["companies"] else None
    person_id = line.get("contact_id") if line.get("contact_id") in ids["people"] else None
    kind = str(line.get("kind") or "note")[:24]
    text = str(line.get("text") or "")
    xp, tag = 0, None
    if kind == "reply" and person_id and company_id and (company_id, f"reply:{person_id}") not in won:
        xp, tag = REPLY_XP, f"reply:{person_id}"
    elif kind == "stage" and company_id and (found := STAGE_AT_END.search(text)):
        stage = STAGE_WORDS[found.group(1).lower()]
        if (company_id, f"stage:{stage.value}") not in won and company_id in companies:
            xp, tag = STAGE_XP[stage], f"stage:{stage.value}"
    if tag and company_id:
        won.add((company_id, tag))
    return Activity(
        at=_at(line.get("ts")) or datetime.now(UTC),
        kind=kind,
        text=text,
        company_id=company_id,
        person_id=person_id,
        move_id=line.get("action_id") if line.get("action_id") in ids["moves"] else None,
        xp=xp,
        tag=tag,
    )


def radar_item(r: dict[str, Any], companies: set[str]) -> RadarItem:
    state = r.get("status") if r.get("status") in ("new", "added", "dismissed") else "new"
    return RadarItem(
        id=str(r["id"])[:80],
        company=_clip(r.get("company"), 200) or "",
        title=_clip(r.get("title"), 300) or "",
        url=_clip(r.get("url"), 1000) or "",
        posted=_day(r.get("posted")),
        fit=_rank(r.get("fit")) or 0,
        state=state,
        company_id=r.get("company_id") if r.get("company_id") in companies else None,
        data={k: v for k, v in r.items() if k not in ("id", "company", "title", "url", "posted", "fit", "status")},
    )


def magnet(m: dict[str, Any], companies: set[str]) -> Magnet:
    return Magnet(
        id=str(m["id"])[:40],
        company_id=m.get("company_id") if m.get("company_id") in companies else None,
        kind=str(m.get("kind") or "engagement")[:24],
        status=str(m.get("status") or "done")[:16],
        title=_clip(m.get("title"), 300) or "",
        data={k: v for k, v in m.items() if k not in ("id", "company_id", "kind", "status", "title")},
    )


def import_legacy(session: Session, export: dict[str, Any], fx: dict[str, Any] | None = None) -> dict[str, int]:
    """Load an old-tracker export into an empty database, in one transaction. Returns what was loaded."""
    if session.scalar(select(func.count()).select_from(Company)):
        raise ImportRefusedError("The database already has companies; import into an empty one.")
    companies = {c["id"]: company(c) for c in export.get("companies", [])}
    seen: set[str] = set()
    for c in sorted(companies.values(), key=lambda c: (c.rank is None, c.rank, c.id)):
        if c.domain and c.domain in seen:  # one company per domain: the best-ranked keeps it, the rest note it
            c.research = {**c.research, "duplicate_domain": c.domain}
            c.domain = None
        elif c.domain:
            seen.add(c.domain)
    session.add_all(companies.values())
    session.flush()
    people = {p["id"]: person(p) for p in export.get("contacts", []) if p.get("company_id") in companies}
    session.add_all(people.values())
    session.flush()
    moves = [move(a, set(people), set(companies)) for a in export.get("actions", [])]
    reach_seen: set[str] = set()
    kept = []
    for m in moves:  # one reach-out per person; a duplicate would break the unique index
        if m.type is MoveType.REACH and m.person_id:
            if m.person_id in reach_seen:
                continue
            reach_seen.add(m.person_id)
        kept.append(m)
    session.add_all(kept)
    session.flush()
    ids = {"companies": set(companies), "people": set(people), "moves": {m.id for m in kept}}
    won: set[tuple[str, str]] = set()
    lines = sorted(export.get("log", []), key=lambda line: (line.get("ts") or "", line.get("id") or 0))
    session.add_all(activity(line, ids, won, companies) for line in lines)
    for key, value in (export.get("settings") or {}).items():
        if key not in SKIPPED_SETTINGS:
            session.add(Setting(key=key, value=value))
    session.add_all(radar_item(r, set(companies)) for r in export.get("radar", []))
    session.add_all(magnet(m, set(companies)) for m in export.get("magnets", []))
    counts = Counter(
        companies=len(companies),
        people=len(people),
        moves=len(kept),
        activity=len(lines),
        radar=len(export.get("radar", [])),
        magnets=len(export.get("magnets", [])),
    )
    session.flush()
    if fx:
        counts["prospects"] = import_prospects(session, fx)
    session.commit()
    return dict(counts)


def import_prospects(session: Session, fx: dict[str, Any]) -> int:
    """Prospects with their research, plus what was done on each (ticks, notes, drafts)."""
    rows = []
    for raw in fx.get("prospects", []):
        try:
            item = ProspectIn.model_validate({k: v for k, v in raw.items() if k not in FX_MINE})
        except ValidationError:
            continue  # a malformed research row; it comes back with the next daily sync
        rows.append((item, {k: raw[k] for k in FX_MINE if k in raw}))
    fx_board.sync(session, [item for item, _ in rows])
    session.flush()
    for item, mine in rows:
        p = session.get(Prospect, item.id)
        if p is not None:
            p.mine = {"status": "open", **mine}
    if isinstance(fx.get("goals"), dict) and session.get(Setting, "fx_goals") is None:
        session.add(Setting(key="fx_goals", value=fx["goals"]))
    return len(rows)
