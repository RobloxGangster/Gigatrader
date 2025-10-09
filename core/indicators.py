"""Technical indicator utilities."""
from __future__ import annotations

import numpy as np


def average_true_range(high: list[float], low: list[float], close: list[float], period: int = 14) -> float:
    if len(close) < period + 1:
        raise ValueError("Insufficient data for ATR")
    trs = []
    for i in range(1, len(close)):
        high_low = high[i] - low[i]
        high_close = abs(high[i] - close[i - 1])
        low_close = abs(low[i] - close[i - 1])
        trs.append(max(high_low, high_close, low_close))
    return float(np.mean(trs[-period:]))


def relative_strength_index(close: list[float], period: int = 14) -> float:
    if len(close) <= period:
        raise ValueError("Insufficient data for RSI")
    deltas = np.diff(close)
    gain = np.where(deltas > 0, deltas, 0)
    loss = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gain[-period:])
    avg_loss = np.mean(loss[-period:])
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def rolling_zscore(series: list[float], window: int = 20) -> float:
    if len(series) < window:
        raise ValueError("Insufficient data for z-score")
    window_data = np.array(series[-window:])
    return float((window_data[-1] - window_data.mean()) / window_data.std(ddof=1))


def momentum(series: list[float], lookback: int = 10) -> float:
    if len(series) <= lookback:
        raise ValueError("Insufficient data for momentum")
    return float(series[-1] - series[-1 - lookback])


def opening_range_breakout(high: list[float], low: list[float], open_: list[float], window: int = 5) -> float:
    if len(high) < window:
        raise ValueError("Insufficient data for ORB")
    range_high = max(high[:window])
    range_low = min(low[:window])
    return float(open_[-1] > range_high) - float(open_[-1] < range_low)
