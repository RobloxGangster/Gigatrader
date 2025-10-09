"""Clock utilities for trading sessions."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Protocol


class ClockProvider(Protocol):
    """Protocol for broker clock responses."""

    async def clock(self) -> dict:
        ...


@dataclass(slots=True)
class MarketClock:
    timestamp: dt.datetime
    is_open: bool
    next_open: dt.datetime
    next_close: dt.datetime

    @classmethod
    def from_alpaca(cls, payload: dict) -> "MarketClock":
        """Create from Alpaca clock payload."""

        return cls(
            timestamp=dt.datetime.fromisoformat(payload["timestamp"]),
            is_open=payload.get("is_open", False),
            next_open=dt.datetime.fromisoformat(payload["next_open"]),
            next_close=dt.datetime.fromisoformat(payload["next_close"]),
        )
