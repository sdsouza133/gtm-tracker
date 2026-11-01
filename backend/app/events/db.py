"""Sessions for the worker's jobs, on the tracker's engine."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

from sqlalchemy import CursorResult, Result
from sqlalchemy.orm import Session

from app.db import session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    """A session that commits on success and rolls back on any error."""
    session = session_factory()()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def rowcount(result: Result[Any]) -> int:
    """Rows touched by an UPDATE or DELETE. SQLAlchemy types `Session.execute` as a plain Result, but for those
    statements it is a CursorResult, which carries the count."""
    return int(cast(CursorResult[Any], result).rowcount or 0)
