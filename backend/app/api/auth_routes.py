"""Sign in, sign out, and who's signed in."""

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.auth import (
    AppSettings,
    DbSession,
    GoogleSignInError,
    current_session,
    end_session,
    google_email,
    locked_out,
    password_ok,
    record_attempt,
    start_session,
)
from app.config import Settings
from app.models import LoginSession

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginBody(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class GoogleBody(BaseModel):
    credential: str = Field(min_length=1, max_length=4096)  # the ID token from Google's sign-in button


class Me(BaseModel):
    signed_in: bool
    csrf: str | None = None
    open_access: bool = False  # no login: the front end hides sign-in and sign-out
    # How the sign-in page offers to sign in: Google's button for this client ID, and the password form if one is set.
    google_client_id: str | None = None
    password_login: bool = False


def _me(settings: Settings, row: LoginSession | None) -> Me:
    return Me(
        signed_in=row is not None,
        csrf=row.csrf if row else None,
        google_client_id=settings.google_client_id,
        password_login=settings.password_hash is not None,
    )


@router.post("/login")
def login(body: LoginBody, response: Response, session: DbSession, settings: AppSettings) -> Me:
    if locked_out(session, settings):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many tries. Wait 15 minutes and try again.")
    ok = password_ok(body.password, settings)
    record_attempt(session, ok=ok)
    if not ok:
        session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "That password isn't right.")
    row = start_session(session, response, settings)
    session.commit()
    return _me(settings, row)


@router.post("/google")
def google(body: GoogleBody, response: Response, session: DbSession, settings: AppSettings) -> Me:
    if settings.google_client_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Google sign-in isn't set up.")
    if locked_out(session, settings):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many tries. Wait 15 minutes and try again.")
    try:
        google_email(body.credential, settings)
    except GoogleSignInError as exc:
        record_attempt(session, ok=False)
        session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    record_attempt(session, ok=True)
    row = start_session(session, response, settings)
    session.commit()
    return _me(settings, row)


@router.post("/logout")
def logout(request: Request, response: Response, session: DbSession, settings: AppSettings) -> Me:
    end_session(session, request, response, settings)
    session.commit()
    return _me(settings, None)


@router.get("/me")
def me(request: Request, session: DbSession, settings: AppSettings) -> Me:
    if settings.open_access:
        return Me(signed_in=True, open_access=True)
    return _me(settings, current_session(request, session, settings))
