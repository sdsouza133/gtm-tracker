"""Login for the one user, and the guards every API route uses.

The user signs in with Google (an account in ALLOWED_EMAILS) or with the password. A session is a random token in an
HttpOnly cookie; only its hash is stored, so a copy of the database can't be used to sign in. Changes need the session's
CSRF token in the `X-CSRF-Token` header (the front end reads it from /api/auth/me). Automation (the daily refresh) can
instead send `Authorization: Bearer <API_TOKEN>`.
"""

import hashlib
import hmac
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request, Response, status
from google.auth.exceptions import GoogleAuthError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
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


class GoogleSignInError(Exception):
    """A Google sign-in that can't be let in; the message says why, for the person signing in."""


def google_email(credential: str, settings: Settings) -> str:
    """The email in a Google ID token, once Google's signature, our client ID, the expiry and the issuer check out,
    Google has verified the address, and it's one of ALLOWED_EMAILS."""
    if settings.google_client_id is None:
        raise GoogleSignInError("Google sign-in isn't set up.")
    try:
        # google-auth leaves this function unannotated; it returns the token's claims
        claims: Mapping[str, object] = id_token.verify_oauth2_token(  # type: ignore[no-untyped-call]
            credential, google_requests.Request(), settings.google_client_id
        )
    except (ValueError, GoogleAuthError) as exc:  # a bad, expired or foreign token, or Google's keys didn't load
        raise GoogleSignInError("Couldn't confirm that Google sign-in. Try again.") from exc
    email = str(claims.get("email") or "").lower()
    if claims.get("email_verified") is not True:
        raise GoogleSignInError("Google hasn't verified that account's email, so it can't sign in here.")
    if not email or email not in settings.allowed_emails:
        raise GoogleSignInError(f"{email or 'That account'} isn't allowed to sign in here.")
    return email


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
    return hmac.compare_digest(header[7:].strip().encode(), settings.api_token.get_secret_value().encode())


def require_user(request: Request, session: DbSession, settings: AppSettings) -> None:
    """Signed in (or the automation token), and for changes, the CSRF header matches. With OPEN_ACCESS on, everyone
    is let in: there is no session to protect."""
    if settings.open_access or _bearer_ok(request, settings):
        return
    row = current_session(request, session, settings)
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in first.")
    if request.method not in SAFE_METHODS:
        sent = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(sent.encode(), row.csrf.encode()):  # bytes: a non-ASCII header can't raise
            raise HTTPException(status.HTTP_403_FORBIDDEN, "This page is out of date. Reload it and try again.")


SignedIn = Depends(require_user)
