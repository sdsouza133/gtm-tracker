"""The events tool's settings."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.events.config import EventsSettings


def test_defaults_need_nothing_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EVENTS_WORKER")  # the tests' own setting
    settings = EventsSettings(providers="real")
    assert settings.run_budget_usd == Decimal("3.00")
    assert settings.daily_cap_usd == Decimal("20.00")
    assert settings.worker is True
    assert settings.missing() == ["ANTHROPIC_API_KEY", "APIFY_TOKEN", "APOLLO_API_KEY"]


def test_fakes_need_no_keys() -> None:
    assert EventsSettings(providers="fake").missing() == []


def test_the_keys_are_the_trackers_own(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a-key")
    monkeypatch.setenv("APIFY_TOKEN", "an-apify-token")
    monkeypatch.setenv("APOLLO_API_KEY", " ")  # blank: not set
    monkeypatch.setenv("EVENTS_DAILY_CAP_USD", "5")
    settings = EventsSettings(providers="real")
    assert settings.missing() == ["APOLLO_API_KEY"]
    assert settings.daily_cap_usd == Decimal("5")


def test_a_blank_knob_means_its_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVENTS_RUN_BUDGET_USD", "")
    assert EventsSettings().run_budget_usd == Decimal("3.00")


def test_analysis_fits_in_the_run_budget() -> None:
    with pytest.raises(ValidationError, match="ANALYSIS_BUDGET_USD"):
        EventsSettings(run_budget_usd="1.00", analysis_budget_usd="2.00")


def test_a_stale_job_is_at_least_three_heartbeats_old() -> None:
    with pytest.raises(ValidationError, match="three heartbeats"):
        EventsSettings(worker_heartbeat_seconds=60, worker_stale_after_seconds=120)


@pytest.mark.parametrize(
    ("raw", "statuses"),
    [("verified", ("verified",)), ("Verified, likely to engage", ("verified", "likely to engage"))],
)
def test_accepted_email_statuses_are_a_list(raw: str, statuses: tuple[str, ...]) -> None:
    assert EventsSettings(accepted_email_statuses=raw).accepted_email_statuses == statuses
