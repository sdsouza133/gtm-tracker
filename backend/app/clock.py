"""One rule for "today": the calendar day in the configured time zone (America/Toronto by default). Every date the
app writes or compares comes from here, so a tick at 9 PM in Toronto lands on Toronto's day, not UTC's."""

from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import Depends

from app.config import Settings, get_settings

SATURDAY = 5


def now() -> datetime:
    return datetime.now(UTC)


def get_today(settings: Annotated[Settings, Depends(get_settings)]) -> date:
    return datetime.now(settings.tz).date()


Today = Annotated[date, Depends(get_today)]


def local_day(at: datetime, settings: Settings) -> date:
    return at.astimezone(settings.tz).date()


def is_weekday(d: date) -> bool:
    return d.weekday() < SATURDAY


def weekday_on_or_after(d: date) -> date:
    while not is_weekday(d):
        d += timedelta(days=1)
    return d


def next_weekday(d: date) -> date:
    return weekday_on_or_after(d + timedelta(days=1))


def add_business_days(d: date, n: int) -> date:
    """`n` working days (Monday to Friday) after `d`."""
    while n > 0:
        d += timedelta(days=1)
        if is_weekday(d):
            n -= 1
    return d
