"""The events tool's tests. Its jobs commit through their own sessions (the worker's `session_scope`), so these tests
can't run inside a rolled-back transaction like the rest: each gets a session on the migrated test database, and the
ev_ tables (and any companies a test made) are emptied afterwards."""

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.db import session_factory
from app.events.config import EventsSettings, get_events_settings
from app.events.models import Base

# Tests never read a developer's .env, nor EVENTS_* settings or service keys exported in their shell, which could
# switch them to real services.
EventsSettings.model_config["env_file"] = None
for _variable in [v for v in os.environ if v.startswith("EVENTS_")]:
    del os.environ[_variable]
for _variable in ("ANTHROPIC_API_KEY", "APIFY_TOKEN", "APOLLO_API_KEY"):
    os.environ.pop(_variable, None)
os.environ["EVENTS_PROVIDERS"] = "fake"
os.environ["EVENTS_WORKER"] = "false"  # no worker thread behind a test client: tests run the jobs themselves


@pytest.fixture(autouse=True)
def _fresh_settings() -> Iterator[None]:
    """Each test sees the environment as it is now, not as a previous test left the cached settings."""
    get_events_settings.cache_clear()
    yield
    get_events_settings.cache_clear()


def truncate_events_tables(engine: Engine) -> None:
    tables = [table.name for table in Base.metadata.sorted_tables if table.name.startswith("ev_")]
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(tables)}, companies RESTART IDENTITY CASCADE"))


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:  # replaces the rolled-back session the tracker's own tests use
    """A session on the migrated test database, committing for real; the events tables are emptied afterwards."""
    session = session_factory()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        truncate_events_tables(engine)
