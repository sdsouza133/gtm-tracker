"""Sign in, sign out, and who's signed in."""

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.auth import (
    AppSettings,
    DbSession,
    current_session,
    end_session,
    locked_out,
    password_ok,
    record_attempt,
    start_session,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginBody(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class Me(BaseModel):
    signed_in: bool
    csrf: str | None = None


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
    return Me(signed_in=True, csrf=row.csrf)


@router.post("/logout")
def logout(request: Request, response: Response, session: DbSession, settings: AppSettings) -> Me:
    end_session(session, request, response, settings)
    session.commit()
    return Me(signed_in=False)


@router.get("/me")
def me(request: Request, session: DbSession, settings: AppSettings) -> Me:
    row = current_session(request, session, settings)
    return Me(signed_in=row is not None, csrf=row.csrf if row else None)
