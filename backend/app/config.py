"""Settings, read once from the environment. Nothing secret has a default."""

from functools import lru_cache
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(description="SQLAlchemy URL, for example postgresql+psycopg://user:pass@host/db")
    # The one user's password, as an argon2 hash (make one with `python -m app.cli hash-password`).
    password_hash: SecretStr | None = None
    # No login at all: anyone with the address can use the tracker. Has to be turned on on purpose; a missing
    # password never opens the app.
    open_access: bool = False
    # Sign in with Google: the OAuth web client's ID (public, it's in every page), and the Google accounts let in.
    google_client_id: str | None = None
    allowed_emails: Annotated[list[str], NoDecode] = []  # comma-separated in the environment
    # Signs nothing by itself; mixed into session token hashing so a leaked database can't be replayed elsewhere.
    secret_key: SecretStr = Field(min_length=32)
    timezone: str = "America/Toronto"
    session_days: int = Field(default=180, ge=1, le=365)
    # Behind Railway's proxy the app is served over HTTPS; locally it isn't.
    secure_cookies: bool = True
    # Login attempts allowed per 15 minutes before the form locks for a while.
    login_attempts: int = Field(default=8, ge=3, le=50)
    # Serve the built front end from this folder when it exists (the Docker image puts it here).
    static_dir: str = "static"
    # Optional tokens for automation (the daily refresh) to call the API without a browser session.
    api_token: SecretStr | None = None
    # The job radar's paid searches (LinkedIn, Google, hiring posts) run only with an Apify token; job boards are free.
    apify_token: SecretStr | None = None
    # Run the radar every morning (at radar_config.hour, local time). Off in tests and one-off scripts.
    radar_schedule: bool = True

    @field_validator("allowed_emails", mode="before")
    @classmethod
    def _split_emails(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.split(",")
        if isinstance(value, list):
            return [str(email).strip().lower() for email in value if str(email).strip()]
        return value

    @field_validator("google_client_id")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return (value or "").strip() or None  # GOOGLE_CLIENT_ID= in .env means "not set up"

    @field_validator("password_hash", mode="before")
    @classmethod
    def _no_blank_password(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value  # PASSWORD_HASH= means "no password"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # the required fields come from the environment
