import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.auth import SignedIn
from app.config import get_settings
from app.main import create_app
from tests.conftest import PASSWORD


def test_health_endpoints(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").status_code == 200


def test_security_headers_on_every_response(client: TestClient) -> None:
    r = client.get("/healthz")
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-request-id"]


def test_signed_out_by_default(client: TestClient) -> None:
    assert client.get("/api/auth/me").json() == {"signed_in": False, "csrf": None, "open_access": False}


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
    ("POST", "/api/restore"),
]


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
    ids = {"c1": "{company_id}", "p1": "{person_id}", "m1": "{move_id}", "x1": "{prospect_id}"}
    covered = {(m, "/".join(ids.get(part, part) for part in p.split("/"))) for m, p in PROTECTED}
    assert routes == covered


def test_open_access_lets_everyone_in_but_only_when_turned_on(client: TestClient) -> None:
    assert client.get("/api/companies").status_code == 401
    open_settings = get_settings().model_copy(update={"open_access": True})
    client.app.dependency_overrides[get_settings] = lambda: open_settings  # type: ignore[attr-defined]
    assert client.get("/api/auth/me").json() == {"signed_in": True, "csrf": None, "open_access": True}
    assert client.get("/api/companies").status_code == 200
    assert client.post("/api/companies", json={"name": "Open Example"}).status_code == 201  # no CSRF needed
