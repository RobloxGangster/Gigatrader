"""Lightweight market regime detector utilities."""

from __future__ import annotations

from collections import deque
from typing import Deque


class RegimeDetector:
    """Detect a basic trending vs choppy regime using ATR / range."""

    def __init__(self, window: int = 20) -> None:
        if window <= 1:
            raise ValueError("window must be greater than 1")
        self.window = window
        self.highs: Deque[float] = deque(maxlen=window)
        self.lows: Deque[float] = deque(maxlen=window)
        self.closes: Deque[float] = deque(maxlen=window)

    def update(self, high: float, low: float, close: float) -> str:
        """Return the latest regime label after ingesting a bar."""

        self.highs.append(high)
        self.lows.append(low)
        self.closes.append(close)

        if len(self.closes) < 2:
            return "unknown"

        range_high = max(self.highs)
        range_low = min(self.lows)
        price_range = max(range_high - range_low, 1e-9)

        closes = list(self.closes)
        atr_sum = 0.0
        for prev, curr in zip(closes, closes[1:]):
            atr_sum += abs(curr - prev)
        atr = atr_sum / (len(closes) - 1)

        ratio = atr / price_range
        return "choppy" if ratio > 0.25 else "trending"
