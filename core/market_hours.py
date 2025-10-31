"""Helpers for determining US equity market trading hours."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

_EASTERN = ZoneInfo("America/New_York")
_OPEN_TIME = time(9, 30)
_CLOSE_TIME = time(16, 0)


def _normalize_now(now: datetime | None = None) -> datetime:
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(_EASTERN)


def market_is_open(now: datetime | None = None) -> bool:
    """Return True if the regular US equity session is open for the provided time."""

    local = _normalize_now(now)
    if local.weekday() >= 5:  # Saturday/Sunday
        return False
    open_dt = datetime.combine(local.date(), _OPEN_TIME, tzinfo=_EASTERN)
    close_dt = datetime.combine(local.date(), _CLOSE_TIME, tzinfo=_EASTERN)
    return open_dt <= local < close_dt


def seconds_until_open(now: datetime | None = None) -> float:
    """Return the seconds until the next regular session open."""

    local = _normalize_now(now)
    # If market already open, next open is next business day
    if market_is_open(local):
        local = local + timedelta(days=1)

    days_ahead = 0
    while True:
        candidate = local + timedelta(days=days_ahead)
        if candidate.weekday() < 5:
            open_dt = datetime.combine(candidate.date(), _OPEN_TIME, tzinfo=_EASTERN)
            if local <= open_dt:
                delta = open_dt - local
                return max(delta.total_seconds(), 0.0)
        days_ahead += 1


def market_state(now: datetime | None = None) -> str:
    """Return a string describing market state ("open" or "closed")."""

    return "open" if market_is_open(now) else "closed"


__all__ = ["market_is_open", "seconds_until_open", "market_state"]
