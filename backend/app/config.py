"""Settings, read once from the environment. Nothing secret has a default."""

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(description="SQLAlchemy URL, for example postgresql+psycopg://user:pass@host/db")
    # The one user's password, as an argon2 hash (make one with `python -m app.cli hash-password`).
    password_hash: SecretStr | None = None
    # Signs nothing by itself; mixed into session token hashing so a leaked database can't be replayed elsewhere.
    secret_key: SecretStr = Field(min_length=32)
    timezone: str = "America/Toronto"
    session_days: int = Field(default=30, ge=1, le=90)
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

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # the required fields come from the environment
