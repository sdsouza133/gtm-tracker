"""Login for the one user, and the guards every API route uses.

A session is a random token in an HttpOnly cookie; only its hash is stored, so a copy of the database can't be used to
sign in. Changes need the session's CSRF token in the `X-CSRF-Token` header (the front end reads it from /api/auth/me).
Automation (the daily refresh) can instead send `Authorization: Bearer <API_TOKEN>`.
"""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.models import LoginAttempt, LoginSession

COOKIE = "gt_session"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
ATTEMPT_WINDOW = timedelta(minutes=15)
_hasher = PasswordHasher()

DbSession = Annotated[Session, Depends(get_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def now() -> datetime:
    return datetime.now(UTC)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def _token_hash(token: str, settings: Settings) -> str:
    key = settings.secret_key.get_secret_value().encode()
    return hmac.new(key, token.encode(), hashlib.sha256).hexdigest()


def password_ok(password: str, settings: Settings) -> bool:
    if settings.password_hash is None:
        return False
    try:
        return _hasher.verify(settings.password_hash.get_secret_value(), password)
    except (VerificationError, InvalidHashError):
        return False


def locked_out(session: Session, settings: Settings) -> bool:
    since = now() - ATTEMPT_WINDOW
    failures = session.scalar(
        select(func.count()).select_from(LoginAttempt).where(LoginAttempt.at >= since, LoginAttempt.ok.is_(False))
    )
    return (failures or 0) >= settings.login_attempts


def record_attempt(session: Session, *, ok: bool) -> None:
    session.add(LoginAttempt(ok=ok, at=now()))
    session.execute(delete(LoginAttempt).where(LoginAttempt.at < now() - timedelta(days=7)))


def start_session(session: Session, response: Response, settings: Settings) -> LoginSession:
    token = secrets.token_urlsafe(32)
    row = LoginSession(
        token_hash=_token_hash(token, settings),
        expires_at=now() + timedelta(days=settings.session_days),
        csrf=secrets.token_urlsafe(24),
    )
    session.add(row)
    session.execute(delete(LoginSession).where(LoginSession.expires_at < now()))
    response.set_cookie(
        COOKIE,
        token,
        max_age=settings.session_days * 86400,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )
    return row


def end_session(session: Session, request: Request, response: Response, settings: Settings) -> None:
    token = request.cookies.get(COOKIE)
    if token:
        session.execute(delete(LoginSession).where(LoginSession.token_hash == _token_hash(token, settings)))
    response.delete_cookie(COOKIE, path="/")


def current_session(request: Request, session: Session, settings: Settings) -> LoginSession | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    row = session.get(LoginSession, _token_hash(token, settings))
    if row is None or row.expires_at <= now():
        return None
    return row


def _bearer_ok(request: Request, settings: Settings) -> bool:
    header = request.headers.get("authorization", "")
    if settings.api_token is None or not header.lower().startswith("bearer "):
        return False
    return hmac.compare_digest(header[7:].strip(), settings.api_token.get_secret_value())


def require_user(request: Request, session: DbSession, settings: AppSettings) -> None:
    """Signed in (or the automation token), and for changes, the CSRF header matches."""
    if _bearer_ok(request, settings):
        return
    row = current_session(request, session, settings)
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in first.")
    if request.method not in SAFE_METHODS:
        sent = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(sent, row.csrf):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "This page is out of date. Reload it and try again.")


SignedIn = Depends(require_user)
