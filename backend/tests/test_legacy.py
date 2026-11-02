"""Importing the first tracker's export, and backups. All of the data here is made up."""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, delete, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.backup import FILL_LOCK, RestoreRefusedError, is_empty, restore, stream, tables
from app.config import get_settings
from app.legacy import ImportRefusedError, import_legacy
from app.models import Activity, Company, Move, MoveStatus, Person, Prospect, RadarItem, Setting, Stage
from tests import factories as f


def legacy_export() -> dict[str, Any]:
    return {
        "companies": [
            {
                "id": "c1",
                "name": "Acme Example",
                "domain": "Acme.example",
                "stage": "contacted",
                "rank": 1,
                "posted": "2026-10-20",
                "score": "4.5",
                "tam": 4,
                "canada_verdict": "strong",
            },
            {
                "id": "c2",
                "name": "Acme Twin",
                "domain": "acme.example",
                "stage": "parked",
                "parked_why": "stale_role",
                "parked_reason": "Old role",
                "rank": "999",
            },
            {"id": "c3", "name": "Odd Stage", "stage": "somewhere", "posted": ""},
        ],
        "contacts": [
            {
                "id": "p1",
                "company_id": "c1",
                "name": "Ana Example",
                "status": "replied",
                "role_in_hire": "approver",
                "hm_confidence": "likely",
                "hm_why": "Posted the role",
                "why_motive": "Growth",
                "drafts": [{"type": "li_note", "subject": "", "body": "Hi"}],
            },
            {
                "id": "p2",
                "company_id": "c1",
                "name": "Bo Example",
                "status": "weird",
                "role_in_hire": "intern",
                "hm_confidence": "",
            },
            {"id": "p3", "company_id": "gone", "name": "Orphan"},
        ],
        "actions": [
            {
                "id": "rp1",
                "type": "reach",
                "company_id": "c1",
                "contact_id": "p1",
                "title": "Reach out to Ana",
                "due": "2026-10-20",
                "day0": "2026-10-20",
                "status": "done",
                "steps": {"email": "2026-10-20", "request": "2026-10-20"},
                "replied": "2026-10-22",
                "next": "replied",
            },
            {
                "id": "rp1b",
                "type": "reach",
                "company_id": "c1",
                "contact_id": "p1",
                "title": "Duplicate",
                "due": "2026-10-20",
                "status": "open",
            },
            {
                "id": "rp2",
                "type": "reach",
                "company_id": "c1",
                "contact_id": "p2",
                "title": "Reach out to Bo",
                "due": "2026-10-26",
                "day0": "2026-10-26",
                "status": "open",
            },
            {
                "id": "a1",
                "type": "apply",
                "company_id": "c1",
                "title": "Apply: GTM Engineer",
                "due": "2026-10-21",
                "status": "done",
                "done_at": "2026-10-21T14:00:00+00:00",
                "url": "https://jobs.example/1",
            },
            {
                "id": "a2",
                "type": "mystery",
                "company_id": "gone",
                "title": "Something",
                "due": "",
                "status": "open",
                "created_at": "2026-10-01T00:00:00Z",
            },
        ],
        "log": [
            {
                "id": 1,
                "ts": "2026-10-22T15:00:00+00:00",
                "kind": "reply",
                "text": "Ana Example replied",
                "company_id": "c1",
                "contact_id": "p1",
            },
            {
                "id": 2,
                "ts": "2026-10-22T16:00:00+00:00",
                "kind": "reply",
                "text": "Ana Example replied again",
                "company_id": "c1",
                "contact_id": "p1",
            },
            {
                "id": 3,
                "ts": "2026-10-23T16:00:00+00:00",
                "kind": "stage",
                "text": "Acme Example: stage replied → call booked",
                "company_id": "c1",
            },
            {
                "id": 4,
                "ts": "2026-10-24T16:00:00+00:00",
                "kind": "stage",
                "text": "Acme Example: stage moved to call booked",
                "company_id": "c1",
                "action_id": "nope",
            },
        ],
        "settings": {
            "candidate": "Demo Candidate",
            "migrations_done": ["x"],
            "videos": [{"id": "v1"}],
            "fx_goals": {"default": 8},
        },
        "radar": [
            {
                "id": "r1",
                "company": "Beta Example",
                "title": "GTM Engineer",
                "url": "https://jobs.example/2",
                "status": "new",
                "fit": 3,
                "posted": "2026-10-25",
                "flags": ["remote"],
            }
        ],
        "magnets": [
            {"id": "m1", "company_id": "c1", "kind": "engagement", "status": "done", "title": "Engagers", "warm": []}
        ],
    }


def legacy_fx() -> dict[str, Any]:
    return {
        "goals": {"default": 10},
        "prospects": [
            {
                "id": "fx_acme",
                "day": "2026-10-26",
                "rank": 1,
                "name": "Acme Fx",
                "fit": "good",
                "research": {},
                "people": [{"key": "ana", "name": "Ana Example"}],
                "touches": {"ana": {"connect": "2026-10-26"}},
                "status": "open",
                "my_notes": "Warm",
            },
        ],
    }


def test_imports_the_first_tracker(db: Session) -> None:
    counts = import_legacy(db, legacy_export(), legacy_fx())
    assert counts == {"companies": 3, "people": 2, "moves": 4, "activity": 4, "radar": 1, "magnets": 1, "prospects": 1}
    acme, twin, odd = (db.get(Company, i) for i in ("c1", "c2", "c3"))
    assert acme is not None
    assert twin is not None
    assert odd is not None
    assert (acme.domain, acme.score, acme.research["canada_verdict"]) == ("acme.example", 4.5, "strong")
    assert (twin.domain, twin.research["duplicate_domain"], twin.parked_why, twin.rank) == (
        None,
        "acme.example",
        "stale_role",
        999,
    )
    assert (odd.stage, odd.posted) == (Stage.NOT_STARTED, None)
    ana, bo = db.get(Person, "p1"), db.get(Person, "p2")
    assert ana is not None
    assert bo is not None
    assert (ana.why, ana.details["why_motive"], ana.drafts[0]["type"]) == ("Posted the role", "Growth", "li_note")
    assert (bo.status.value, bo.role_in_hire.value, bo.sureness) == ("none", "hiring manager", None)
    assert db.get(Move, "rp1b") is None  # one reach-out per person
    reach = db.get(Move, "rp1")
    assert reach is not None
    assert (reach.status, reach.sequence["next"]) == (MoveStatus.DONE, "replied")
    assert reach.done_at is not None
    assert (
        reach.done_at.astimezone(get_settings().tz).isoformat() == "2026-10-22T12:00:00-04:00"
    )  # the day they replied
    rp2 = db.get(Move, "rp2")
    assert rp2 is not None
    assert rp2.sequence["next"] == "email+request"
    a2 = db.get(Move, "a2")
    assert a2 is not None
    assert (a2.type.value, a2.company_id, str(a2.due)) == ("custom", None, "2026-10-01")
    wins = db.execute(select(Activity.tag, Activity.xp).where(Activity.xp > 0).order_by(Activity.id)).all()
    assert [tuple(w) for w in wins] == [("reply:p1", 10), ("stage:call_booked", 25)]  # each win counted once
    assert db.get(Setting, "migrations_done") is None
    assert db.get(Setting, "videos") is not None
    radar = db.get(RadarItem, "r1")
    assert radar is not None
    assert (radar.state, radar.data["flags"]) == ("new", ["remote"])
    p = db.get(Prospect, "fx_acme")
    assert p is not None
    assert (p.mine["touches"], p.mine["my_notes"]) == ({"ana": {"connect": "2026-10-26"}}, "Warm")
    with pytest.raises(ImportRefusedError):
        import_legacy(db, legacy_export())


def test_refuses_a_database_with_data_or_a_prospect_it_cant_read(db: Session) -> None:
    broken = {"prospects": [{"id": "bad id!", "day": "2026-10-26", "rank": 2, "name": "Broken"}]}
    with pytest.raises(ImportRefusedError, match="bad id!"):  # its ticks and notes would be lost, so nothing loads
        import_legacy(db, legacy_export(), broken)
    db.rollback()
    db.add(Setting(key="videos", value=[]))
    db.flush()
    with pytest.raises(ImportRefusedError, match="already has data"):
        import_legacy(db, legacy_export())


def test_a_backup_restores_into_an_empty_database(db: Session) -> None:
    import_legacy(db, legacy_export(), legacy_fx())
    backup = json.loads("".join(stream(db)))
    assert backup["version"] == 1
    assert {len(backup[t]) for t in ("companies", "people", "moves")} == {3, 2, 4}
    assert "login_sessions" not in backup
    assert not [name for name in backup if name.startswith("ev_")]  # the events tool's 30-day data isn't kept
    with pytest.raises(RestoreRefusedError):
        restore(db, backup)
    for table in reversed(tables()):  # empty the database, children first
        db.execute(delete(table))
    counts = restore(db, backup)
    assert (counts["companies"], counts["moves"], counts["prospects"]) == (3, 4, 1)
    reach = db.get(Move, "rp1")
    assert reach is not None
    assert reach.sequence["replied"] == "2026-10-22"
    with pytest.raises(RestoreRefusedError):
        restore(db, {**backup, "version": 99})
    with pytest.raises(RestoreRefusedError, match="missing activity"):
        restore(db, {k: v for k, v in backup.items() if k != "activity"})


def test_only_one_restore_at_a_time(connection: Connection) -> None:
    engine = connection.engine
    with sessionmaker(bind=engine)() as first, engine.connect() as other:
        is_empty(first)  # a restore has checked and is filling
        assert other.scalar(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": FILL_LOCK}) is False
        first.rollback()  # done: the next restore may check
        assert other.scalar(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": FILL_LOCK}) is True


def test_backup_download(signed_in: TestClient, db: Session) -> None:
    f.company(db, name="Downloaded Example")
    r = signed_in.get("/api/export")
    assert r.status_code == 200
    assert r.headers["content-disposition"] == 'attachment; filename="gtm-tracker-2026-10-26.json"'
    assert [c["name"] for c in r.json()["companies"]] == ["Downloaded Example"]


def test_restore_over_the_api_only_into_an_empty_tracker(signed_in: TestClient, db: Session) -> None:
    import_legacy(db, legacy_export(), legacy_fx())
    backup = json.loads("".join(stream(db)))
    assert signed_in.post("/api/restore", json=backup).status_code == 409  # it already has data
    for table in reversed(tables()):
        db.execute(delete(table))
    r = signed_in.post("/api/restore", json=backup)
    assert r.status_code == 200, r.text
    assert (r.json()["companies"], r.json()["prospects"]) == (3, 1)
