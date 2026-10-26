from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.auth import SignedIn
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
    assert client.get("/api/auth/me").json() == {"signed_in": False, "csrf": None}


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
