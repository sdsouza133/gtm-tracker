"""Tests run against a real Postgres (TEST_DATABASE_URL), migrated once; each test runs in a transaction that's rolled
back, so tests don't see each other's rows."""

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Connection, create_engine, make_url
from sqlalchemy.orm import Session

# A Monday, so the working-day rules have a known shape. Tests that need "now" freeze it to this day too.
TODAY = date(2026, 10, 26)
NOON = datetime(2026, 10, 26, 16, 0, tzinfo=UTC)  # noon in Toronto

TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://gt:gt@localhost:5432/gt_test")
PASSWORD = "correct horse battery staple"

os.environ["DATABASE_URL"] = TEST_DB
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-long-enough-0123456789")
os.environ["SECURE_COOKIES"] = "false"
os.environ["STATIC_DIR"] = "/nonexistent"
os.environ["API_TOKEN"] = "automation-token-for-tests"

from app.auth import hash_password  # noqa: E402  (the environment above must be set first)

os.environ["PASSWORD_HASH"] = hash_password(PASSWORD)

from app.clock import get_today  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import get_session  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services import outreach  # noqa: E402


@pytest.fixture(scope="session")
def engine():
    name = make_url(TEST_DB).database or ""
    if not name.endswith("_test"):  # the fixture drops every table: never point it at a real database
        pytest.exit(f"Refusing to reset {name!r}: the test database's name must end in _test.", returncode=2)
    get_settings.cache_clear()
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "migrations"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    eng = create_engine(TEST_DB)
    yield eng
    eng.dispose()


@pytest.fixture
def connection(engine) -> Iterator[Connection]:  # type: ignore[no-untyped-def]
    with engine.connect() as conn:
        outer = conn.begin()
        yield conn
        outer.rollback()


@pytest.fixture
def db(connection: Connection) -> Iterator[Session]:
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        yield session


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    app = create_app()

    def _session() -> Iterator[Session]:
        yield db

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_today] = lambda: TODAY
    with TestClient(app) as c:
        yield c


@pytest.fixture
def signed_in(client: TestClient) -> TestClient:
    """A client with a session and the CSRF header set, like the front end after signing in."""
    r = client.post("/api/auth/login", json={"password": PASSWORD})
    assert r.status_code == 200
    client.headers["X-CSRF-Token"] = r.json()["csrf"]
    return client


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch: pytest.MonkeyPatch) -> datetime:
    """Moves finished in a test are finished at noon on TODAY."""
    monkeypatch.setattr(outreach, "now", lambda: NOON)
    return NOON
