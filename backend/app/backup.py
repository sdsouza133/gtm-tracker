"""A full backup as one JSON document, and loading one back into an empty database.

Every table is included except sign-in state and the events tool's (ev_*): those hold LinkedIn posts and Apollo
lookups that are deleted after 30 days, and a restored backup would bring them back. Rows are written column by column,
so a backup made today restores into the same schema version; restore runs the tables in foreign-key order inside one
transaction.
"""

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, Engine, Table, exists, insert, select, text
from sqlalchemy.orm import Session

from app.models import Base

VERSION = 1
SKIP = frozenset({"login_sessions", "login_attempts"})
EVENTS_TOOL = "ev_"
BATCH = 500


def tables() -> list[Table]:
    return [t for t in Base.metadata.sorted_tables if t.name not in SKIP and not t.name.startswith(EVENTS_TOOL)]


def _plain(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def snapshot(session: Session) -> None:
    """Read every table from one snapshot, so a row added mid-download can't appear without its parent. Ends the
    request's read transaction and starts a repeatable-read one. A session bound to a connection that already has its
    own transaction (the tests) keeps it."""
    if isinstance(session.get_bind(), Engine):
        session.commit()
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})


FILL_LOCK = 7_204_312  # one restore or import at a time


def is_empty(session: Session) -> bool:
    """Nothing in any table a backup or import would fill. Takes a lock held until the transaction ends, so two
    restores can't both find the database empty and both fill it."""
    session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": FILL_LOCK})
    return not any(session.scalar(select(exists().select_from(t))) for t in tables())


def stream(session: Session) -> Iterator[str]:
    """The backup, a piece at a time, so a large tracker never sits whole in memory."""
    snapshot(session)
    yield json.dumps({"version": VERSION, "exported_at": datetime.now(UTC).isoformat()})[:-1]
    for table in tables():
        yield f', "{table.name}": ['
        first = True
        for row in session.execute(select(table)).mappings().yield_per(BATCH):
            yield ("" if first else ",") + json.dumps({k: _plain(v) for k, v in row.items()})
            first = False
        yield "]"
    yield "}"


class RestoreRefusedError(RuntimeError):
    """Restoring would mix a backup into existing data."""


def restore(session: Session, backup: dict[str, Any]) -> dict[str, int]:
    if backup.get("version") != VERSION:
        raise RestoreRefusedError(f"This backup is version {backup.get('version')}; this app reads version {VERSION}.")
    if missing := [t.name for t in tables() if not isinstance(backup.get(t.name), list)]:
        raise RestoreRefusedError(f"This backup is missing {', '.join(missing)}; it may be cut short or edited.")
    if not is_empty(session):
        raise RestoreRefusedError("The database already has data; restore into an empty one.")
    counts = {}
    for table in tables():
        rows = [_typed(table, r) for r in backup[table.name]]
        for i in range(0, len(rows), BATCH):
            session.execute(insert(table), rows[i : i + BATCH])
        counts[table.name] = len(rows)
    if backup.get("activity"):  # keep new history ids after the restored ones
        session.execute(text("SELECT setval(pg_get_serial_sequence('activity', 'id'), (SELECT max(id) FROM activity))"))
    session.commit()
    return counts


def _typed(table: Table, row: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for column in table.columns:
        if column.key not in row:
            continue
        value = row[column.key]
        if isinstance(value, str) and isinstance(column.type, DateTime):
            value = datetime.fromisoformat(value)
        elif isinstance(value, str) and isinstance(column.type, Date):
            value = date.fromisoformat(value)
        out[column.key] = value
    return out
