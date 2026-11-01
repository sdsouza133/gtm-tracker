"""The events tool's settings: its caps and knobs (EVENTS_*), and the API keys it shares with the rest of the tracker.

Every knob has a default, so the tool works with nothing set beyond the keys the tracker already has. The keys are
read under their own names (ANTHROPIC_API_KEY, APIFY_TOKEN, APOLLO_API_KEY): one key per service for the whole
tracker.
"""

from decimal import Decimal
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class EventsSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", env_prefix="EVENTS_", extra="ignore", populate_by_name=True
    )

    # Spend caps for the dollar-billed services, Apify and Claude.
    run_budget_usd: Decimal = Field(default=Decimal("3.00"), gt=0)
    # The part of a run spent before approval. At least what analyze_site reserves, or no run could start.
    analysis_budget_usd: Decimal = Field(default=Decimal("0.50"), ge=Decimal("0.15"))
    daily_cap_usd: Decimal = Field(default=Decimal("20.00"), gt=0)
    # Stops new paid work: no new runs start, and the worker holds every job about to make a paid call until it's
    # unset. A call already made finishes. (The Events page has a switch for new runs too, stored in ev_flags.)
    pause_new_runs: bool = False

    # The background worker, a thread in the web process (EVENTS_WORKER=false turns it off, as in tests).
    worker: bool = True
    worker_poll_seconds: float = Field(default=2.0, gt=0, le=60)
    worker_heartbeat_seconds: int = Field(default=30, ge=1, le=300)
    worker_stale_after_seconds: int = Field(default=300, ge=60)  # no heartbeat for this long: the job is put back

    # Collecting posts: one Apify search per event, whose posts other runs reuse for a few days.
    search_posts_per_query: int = Field(default=50, ge=1, le=200)
    search_cache_days: int = Field(default=3, ge=0, le=30)
    search_poll_seconds: int = Field(default=20, ge=1, le=600)

    # Finding emails. Apollo bills a credit per person it finds, so each run has an allowance of credits rather than
    # dollars. A list holds at most 50 people.
    max_leads: int = Field(default=50, ge=1, le=50)
    apollo_credits_per_run: int = Field(default=150, ge=0, le=1000)
    # How long a person's Apollo data and email check are reused. At most 30: personal data is deleted by then.
    person_cache_days: int = Field(default=30, ge=1, le=30)
    accepted_email_statuses: Annotated[tuple[str, ...], NoDecode] = Field(default=("verified",), min_length=1)
    min_icp_score: int = Field(default=40, ge=0, le=100)
    results_days: int = Field(default=30, ge=1, le=30)

    # External services. "fake" runs everything offline on synthetic data (tests, local work).
    providers: Literal["fake", "real"] = "real"
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY"))
    analyze_model: str = "claude-opus-5-5"
    classify_model: str = "claude-opus-5-5"  # claude-haiku-5-5 costs about 1/40 as much
    analyze_effort: Effort = "medium"
    classify_effort: Effort = "low"
    # Web searches for one event research, plus at most one Claude asked for just as a long turn paused.
    max_web_searches: int = Field(default=4, ge=1, le=20)  # each search's results are most of a plan's cost
    llm_fallbacks: bool = True
    apify_token: SecretStr | None = Field(default=None, validation_alias=AliasChoices("APIFY_TOKEN"))
    apify_actor: str = "harvestapi~linkedin-post-search"
    apify_posted_limit: Literal["week", "month", "3months", "6months"] = "3months"
    apollo_api_key: SecretStr | None = Field(default=None, validation_alias=AliasChoices("APOLLO_API_KEY"))
    # An optional second check of the emails on a list (one credit per address).
    reoon_enabled: bool = False
    reoon_api_key: SecretStr | None = None

    @model_validator(mode="before")
    @classmethod
    def _blank_means_unset(cls, data: Any) -> Any:
        """A blank variable (EVENTS_DAILY_CAP_USD= in a copied .env, a key that isn't set) means "use the default"."""
        if not isinstance(data, dict):
            return data
        return {name: value for name, value in data.items() if not _blank(value)}

    @field_validator("accepted_email_statuses", mode="before")
    @classmethod
    def _comma_separated(cls, value: Any) -> Any:
        """EVENTS_ACCEPTED_EMAIL_STATUSES=verified,likely to engage (Apollo's statuses): a list, in lower case."""
        if isinstance(value, str):
            value = value.split(",")
        if isinstance(value, list | tuple | set | frozenset):
            return tuple(dict.fromkeys(str(item).strip().lower() for item in value if str(item).strip()))
        return value

    @model_validator(mode="after")
    def _consistent(self) -> "EventsSettings":
        if self.analysis_budget_usd > self.run_budget_usd:
            raise ValueError("EVENTS_ANALYSIS_BUDGET_USD can't be more than EVENTS_RUN_BUDGET_USD")
        if self.worker_heartbeat_seconds * 3 > self.worker_stale_after_seconds:
            raise ValueError("EVENTS_WORKER_STALE_AFTER_SECONDS must be at least three heartbeats")
        return self

    def missing(self) -> list[str]:
        """The keys a real run needs that aren't set, by the names to set them under."""
        if self.providers == "fake":
            return []
        keys = {"ANTHROPIC_API_KEY": self.anthropic_api_key, "APIFY_TOKEN": self.apify_token}
        keys["APOLLO_API_KEY"] = self.apollo_api_key
        return [name for name, key in keys.items() if key is None or not key.get_secret_value().strip()]


def _blank(value: Any) -> bool:
    return isinstance(value, str) and not value.strip()


@lru_cache
def get_events_settings() -> EventsSettings:
    return EventsSettings()
