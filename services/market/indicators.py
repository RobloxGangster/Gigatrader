"""Rolling indicator utilities for live market data."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional
import math


Number = float


@dataclass
class RollingRSI:
    """Compute a rolling Relative Strength Index value."""

    period: int = 14
    gains: Deque[Number] = field(init=False)
    losses: Deque[Number] = field(init=False)
    last_close: Optional[Number] = field(default=None, init=False)

    def __post_init__(self) -> None:
        if self.period <= 0:
            raise ValueError("RSI period must be positive")
        self.gains = deque(maxlen=self.period)
        self.losses = deque(maxlen=self.period)

    def update(self, close: Number) -> Optional[Number]:
        if self.last_close is None:
            self.last_close = close
            return None

        change = close - self.last_close
        self.last_close = close

        self.gains.append(max(change, 0.0))
        self.losses.append(max(-change, 0.0))

        if len(self.gains) < self.period:
            return None

        avg_gain = sum(self.gains) / self.period
        avg_loss = sum(self.losses) / self.period
        if math.isclose(avg_loss, 0.0):
            return 100.0

        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))


@dataclass
class RollingATR:
    """Compute a rolling Average True Range value."""

    period: int = 14
    true_ranges: Deque[Number] = field(init=False)
    prev_close: Optional[Number] = field(default=None, init=False)

    def __post_init__(self) -> None:
        if self.period <= 0:
            raise ValueError("ATR period must be positive")
        self.true_ranges = deque(maxlen=self.period)

    def update(self, high: Number, low: Number, close: Number) -> Optional[Number]:
        if self.prev_close is None:
            true_range = high - low
        else:
            true_range = max(
                high - low,
                abs(high - self.prev_close),
                abs(low - self.prev_close),
            )
        self.prev_close = close
        self.true_ranges.append(true_range)

        if len(self.true_ranges) < self.period:
            return None

        return sum(self.true_ranges) / self.period


@dataclass
class RollingZScore:
    """Compute a rolling Z-score for a price series."""

    window: int = 20
    values: Deque[Number] = field(init=False)

    def __post_init__(self) -> None:
        if self.window <= 1:
            raise ValueError("Z-score window must be greater than 1")
        self.values = deque(maxlen=self.window)

    def update(self, value: Number) -> Optional[Number]:
        self.values.append(value)
        if len(self.values) < self.window:
            return None

        mean = sum(self.values) / self.window
        variance = sum((x - mean) ** 2 for x in self.values) / self.window
        std_dev = math.sqrt(variance)
        if math.isclose(std_dev, 0.0):
            return 0.0
        return (self.values[-1] - mean) / std_dev


@dataclass
class OpeningRange:
    """Track an opening range breakout window."""

    minutes: int = 30
    bars_seen: int = field(default=0, init=False)
    high: Optional[Number] = field(default=None, init=False)
    low: Optional[Number] = field(default=None, init=False)
    active: bool = field(default=True, init=False)

    def __post_init__(self) -> None:
        if self.minutes <= 0:
            raise ValueError("Opening range minutes must be positive")

    def reset(self) -> None:
        self.bars_seen = 0
        self.high = None
        self.low = None
        self.active = True

    def update(self, high: Number, low: Number) -> Dict[str, Optional[Number]]:
        if self.active:
            self.bars_seen += 1
            self.high = high if self.high is None else max(self.high, high)
            self.low = low if self.low is None else min(self.low, low)
            if self.bars_seen >= self.minutes:
                self.active = False

        return {"high": self.high, "low": self.low, "active": self.active}

    def breakout(self, price: Number) -> int:
        if self.active or self.high is None or self.low is None:
            return 0
        if price >= self.high:
            return 1
        if price <= self.low:
            return -1
        return 0
