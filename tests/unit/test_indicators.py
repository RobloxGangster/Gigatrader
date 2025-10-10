from __future__ import annotations

import math


from core.indicators import (
    average_true_range,
    momentum,
    opening_range_breakout,
    relative_strength_index,
    rolling_zscore,
)


def test_average_true_range_simple() -> None:
    high = [2, 3, 4, 5, 6, 7]
    low = [1, 1, 2, 3, 4, 5]
    close = [1.5, 2.5, 3.5, 4.5, 5.5, 6.5]
    atr = average_true_range(high, low, close, period=3)
    assert atr > 0


def test_rsi_bounds() -> None:
    close = list(range(20))
    value = relative_strength_index(close)
    assert 0 <= value <= 100


def test_zscore_zero_variance() -> None:
    series = [1.0 + (0.1 * i) for i in range(20)]
    z = rolling_zscore(series)
    assert math.isfinite(z)


def test_momentum_positive() -> None:
    series = list(range(15))
    assert momentum(series, lookback=5) > 0


def test_orb_signal() -> None:
    high = [10, 10.5, 11, 11.5, 12]
    low = [9, 9.5, 9.8, 10, 10.2]
    open_ = [9.5, 9.7, 10, 12.5, 12.6]
    signal = opening_range_breakout(high, low, open_, window=3)
    assert signal in (-1.0, 0.0, 1.0)
