from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.auth import SignedIn
from app.config import Settings, get_settings
from app.main import create_app
from tests.conftest import PASSWORD


def test_health_endpoints(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").status_code == 200


def test_security_headers_on_every_response(client: TestClient) -> None:
    r = client.get("/healthz")
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert "frame-src https://accounts.google.com/gsi/;" in r.headers["content-security-policy"]  # the sign-in button
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-request-id"]


def test_signed_out_by_default(client: TestClient) -> None:
    assert client.get("/api/auth/me").json() == {
        "signed_in": False,
        "csrf": None,
        "open_access": False,
        "google_client_id": None,
        "password_login": True,
    }


def test_wrong_password_is_refused(client: TestClient) -> None:
    r = client.post("/api/auth/login", json={"password": "nope"})
    assert r.status_code == 401
    assert "gt_session" not in r.cookies


def test_login_sets_an_httponly_cookie_and_returns_csrf(client: TestClient) -> None:
    r = client.post("/api/auth/login", json={"password": PASSWORD})
    assert r.status_code == 200
    assert r.json()["csrf"]
    assert "httponly" in r.headers["set-cookie"].lower()
    me = client.get("/api/auth/me").json()
    assert me["signed_in"] is True
    assert me["csrf"] == r.json()["csrf"]


def test_logout_ends_the_session(signed_in: TestClient) -> None:
    signed_in.post("/api/auth/logout")
    assert signed_in.get("/api/auth/me").json()["signed_in"] is False


def test_too_many_failures_lock_the_form(client: TestClient) -> None:
    for _ in range(8):
        client.post("/api/auth/login", json={"password": "wrong"})
    r = client.post("/api/auth/login", json={"password": PASSWORD})
    assert r.status_code == 429


def _guarded(client: TestClient) -> TestClient:
    router = APIRouter()

    @router.get("/api/test/read", dependencies=[SignedIn])
    def read() -> dict[str, bool]:
        return {"ok": True}

    @router.post("/api/test/write", dependencies=[SignedIn])
    def write() -> dict[str, bool]:
        return {"ok": True}

    app: FastAPI = client.app  # type: ignore[assignment]
    app.include_router(router)
    return client


def test_routes_need_a_session(client: TestClient) -> None:
    c = _guarded(client)
    assert c.get("/api/test/read").status_code == 401


def test_changes_need_the_csrf_header(signed_in: TestClient) -> None:
    c = _guarded(signed_in)
    assert c.get("/api/test/read").status_code == 200
    assert c.post("/api/test/write").status_code == 200
    del c.headers["X-CSRF-Token"]
    assert c.post("/api/test/write").status_code == 403


def test_automation_token_works_without_a_session(client: TestClient) -> None:
    c = _guarded(client)
    headers = {"Authorization": "Bearer automation-token-for-tests"}
    assert c.post("/api/test/write", headers=headers).status_code == 200
    assert c.post("/api/test/write", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_non_ascii_tokens_are_refused_not_crashed(signed_in: TestClient) -> None:
    c = _guarded(signed_in)
    odd = "Bearer caf\xe9".encode("latin-1")
    del c.headers["X-CSRF-Token"]
    assert c.post("/api/test/write", headers={b"X-CSRF-Token": "caf\xe9".encode("latin-1")}).status_code == 403
    signed_in.cookies.clear()
    assert c.post("/api/test/write", headers={b"Authorization": odd}).status_code == 401


def test_no_public_api_docs(client: TestClient) -> None:
    assert client.get("/api/docs").status_code == 404
    assert client.get("/api/openapi.json").status_code == 404


RUN = "00000000-0000-4000-8000-000000000001"  # an events run id (a UUID)
PROTECTED = [
    ("GET", "/api/companies"),
    ("POST", "/api/companies"),
    ("GET", "/api/companies/c1"),
    ("PATCH", "/api/companies/c1"),
    ("POST", "/api/companies/c1/promote"),
    ("GET", "/api/people"),
    ("POST", "/api/people"),
    ("PATCH", "/api/people/p1"),
    ("POST", "/api/people/p1/reply"),
    ("POST", "/api/moves"),
    ("PATCH", "/api/moves/m1"),
    ("POST", "/api/moves/m1/steps"),
    ("DELETE", "/api/moves/m1"),
    ("POST", "/api/moves/pull"),
    ("POST", "/api/moves/clear-backlog"),
    ("POST", "/api/companies/c1/enrich"),
    ("POST", "/api/enrich/today"),
    ("GET", "/api/today"),
    ("GET", "/api/stats"),
    ("GET", "/api/plan"),
    ("GET", "/api/activity"),
    ("POST", "/api/activity"),
    ("GET", "/api/settings"),
    ("PATCH", "/api/settings"),
    ("GET", "/api/fx/board"),
    ("GET", "/api/fx/pipeline"),
    ("GET", "/api/fx/prospects"),
    ("PUT", "/api/fx/prospects"),
    ("GET", "/api/fx/prospects/x1"),
    ("PATCH", "/api/fx/prospects/x1"),
    ("GET", "/api/export"),
    ("GET", "/api/radar"),
    ("PATCH", "/api/radar/config"),
    ("POST", "/api/radar/run"),
    ("POST", "/api/radar/items/r1/add"),
    ("POST", "/api/radar/items/r1/dismiss"),
    ("POST", "/api/restore"),
    ("GET", "/api/companies/c1/magnets"),
    ("POST", "/api/companies/c1/magnets"),
    ("GET", "/api/magnets/g1"),
    ("DELETE", "/api/magnets/g1"),
    ("GET", "/api/events"),
    ("POST", "/api/events/runs"),
    ("GET", f"/api/events/runs/{RUN}"),
    ("PUT", f"/api/events/runs/{RUN}/plan"),
    ("POST", f"/api/events/runs/{RUN}/events"),
    ("POST", f"/api/events/runs/{RUN}/cancel"),
    ("GET", f"/api/events/runs/{RUN}/leads"),
    ("PUT", "/api/events/new-runs"),
]
# Open on purpose: a lead magnet report, for whoever holds its link (the token in it is checked).
PUBLIC = {("GET", "/api/public/magnets/{magnet_id}/{token}")}


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_every_tracker_route_needs_a_session(client: TestClient, method: str, path: str) -> None:
    assert client.request(method, path, json={}).status_code == 401


@pytest.mark.parametrize(("method", "path"), [(m, p) for m, p in PROTECTED if m != "GET"])
def test_every_tracker_change_needs_the_csrf_token(signed_in: TestClient, method: str, path: str) -> None:
    assert signed_in.request(method, path, json={}, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    del signed_in.headers["X-CSRF-Token"]
    assert signed_in.request(method, path, json={}).status_code == 403


def test_every_api_route_is_covered_above() -> None:
    """A new /api route has to be added to PROTECTED, so it can't ship without the guard being tested."""
    paths = create_app().openapi()["paths"]
    routes = {
        (method.upper(), path) for path, ops in paths.items() for method in ops if not path.startswith("/api/auth/")
    }
    ids = {
        "c1": "{company_id}",
        "p1": "{person_id}",
        "m1": "{move_id}",
        "x1": "{prospect_id}",
        "r1": "{item_id}",
        "g1": "{magnet_id}",
        RUN: "{run_id}",
    }
    covered = {(m, "/".join(ids.get(part, part) for part in p.split("/"))) for m, p in PROTECTED}
    assert routes == covered | PUBLIC


def test_open_access_lets_everyone_in_but_only_when_turned_on(client: TestClient) -> None:
    assert client.get("/api/companies").status_code == 401
    open_settings = get_settings().model_copy(update={"open_access": True})
    client.app.dependency_overrides[get_settings] = lambda: open_settings  # type: ignore[attr-defined]
    me = client.get("/api/auth/me").json()
    assert (me["signed_in"], me["csrf"], me["open_access"]) == (True, None, True)
    assert client.get("/api/companies").status_code == 200
    assert client.post("/api/companies", json={"name": "Open Example"}).status_code == 201  # no CSRF needed


CLIENT_ID = "test-client.apps.googleusercontent.com"
# The fake verifier reads the claims off the credential's name, so each test says what Google would have vouched for.
TOKENS: dict[str, dict[str, Any]] = {
    "owner": {"email": "Owner@Example.com", "email_verified": True},
    "stranger": {"email": "stranger@example.com", "email_verified": True},
    "unverified": {"email": "owner@example.com", "email_verified": False},
}


def _use(client: TestClient, settings: Settings) -> None:
    client.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]


@pytest.fixture
def google(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Google sign-in set up for owner@example.com, with Google's side faked: no network in tests."""

    def verify(credential: str, request: object, audience: str) -> dict[str, Any]:
        assert isinstance(request, google_requests.Request)
        assert audience == CLIENT_ID
        if credential not in TOKENS:
            raise ValueError("Wrong number of segments in token")
        return {"iss": "https://accounts.google.com", "aud": audience, **TOKENS[credential]}

    monkeypatch.setattr(id_token, "verify_oauth2_token", verify)
    settings = get_settings().model_copy(
        update={"google_client_id": CLIENT_ID, "allowed_emails": ["owner@example.com"]}
    )
    _use(client, settings)
    return client


def test_me_offers_google_sign_in_when_it_is_set_up(google: TestClient) -> None:
    me = google.get("/api/auth/me").json()
    assert me["google_client_id"] == CLIENT_ID
    assert me["signed_in"] is False


def test_an_allowed_google_account_signs_in(google: TestClient) -> None:
    r = google.post("/api/auth/google", json={"credential": "owner"})
    assert r.status_code == 200
    assert r.json()["csrf"]
    assert "httponly" in r.headers["set-cookie"].lower()
    me = google.get("/api/auth/me").json()
    assert me["signed_in"] is True
    assert me["csrf"] == r.json()["csrf"]
    google.headers["X-CSRF-Token"] = me["csrf"]
    assert google.post("/api/companies", json={"name": "Google Example"}).status_code == 201


@pytest.mark.parametrize(
    ("credential", "message"),
    [("stranger", "stranger@example.com isn't allowed"), ("unverified", "hasn't verified"), ("forged", "Couldn't")],
)
def test_other_google_sign_ins_are_refused(google: TestClient, credential: str, message: str) -> None:
    r = google.post("/api/auth/google", json={"credential": credential})
    assert r.status_code == 401
    assert message in r.json()["detail"]
    assert "gt_session" not in r.cookies
    assert google.get("/api/auth/me").json()["signed_in"] is False


def test_google_sign_in_needs_a_client_id(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def verify(*_args: object) -> dict[str, Any]:
        raise AssertionError("there's no client ID to check a token against")

    monkeypatch.setattr(id_token, "verify_oauth2_token", verify)
    _use(client, get_settings().model_copy(update={"allowed_emails": ["owner@example.com"]}))
    assert client.get("/api/auth/me").json()["google_client_id"] is None
    assert client.post("/api/auth/google", json={"credential": "owner"}).status_code == 404


def test_failed_google_sign_ins_count_towards_the_lock(google: TestClient) -> None:
    for _ in range(8):
        google.post("/api/auth/google", json={"credential": "stranger"})
    assert google.post("/api/auth/google", json={"credential": "owner"}).status_code == 429
    assert google.post("/api/auth/login", json={"password": PASSWORD}).status_code == 429


def test_without_a_password_only_google_is_offered(google: TestClient) -> None:
    settings = get_settings().model_copy(
        update={"google_client_id": CLIENT_ID, "allowed_emails": ["owner@example.com"], "password_hash": None}
    )
    _use(google, settings)
    assert google.get("/api/auth/me").json()["password_login"] is False
    assert google.post("/api/auth/google", json={"credential": "owner"}).status_code == 200


def test_allowed_emails_are_read_as_a_comma_separated_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_EMAILS", " Owner@Example.com, second@example.com ,")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "")
    monkeypatch.delenv("SESSION_DAYS", raising=False)
    settings = Settings()
    assert settings.allowed_emails == ["owner@example.com", "second@example.com"]
    assert settings.google_client_id is None
    assert settings.session_days == 180


def test_a_blank_password_hash_means_no_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PASSWORD_HASH", "  ")
    assert Settings().password_hash is None
