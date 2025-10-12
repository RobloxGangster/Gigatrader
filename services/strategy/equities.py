"""Equity strategy implementations for the strategy engine."""

from __future__ import annotations

import os
import time
from typing import Callable, Optional

from services.market.indicators import OpeningRange, RollingRSI
from services.strategy.types import Bar, OrderPlan


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


class EquityStrategy:
    """Opening-range breakout + momentum strategy gated by sentiment."""

    def __init__(
        self,
        *,
        orb_min: Optional[int] = None,
        min_rsi: Optional[int] = None,
        min_senti: Optional[float] = None,
        cooldown: Optional[int] = None,
        max_pos_per_symbol: Optional[int] = None,
        time_fn: Optional[Callable[[], float]] = None,
    ) -> None:
        orb_minutes = orb_min if orb_min is not None else _env_int("STRAT_ORB_MIN", 30)
        self.rsi = RollingRSI(14)
        self.orb = OpeningRange(minutes=orb_minutes)
        self.min_rsi = min_rsi if min_rsi is not None else _env_int("STRAT_MOMENTUM_MIN_RSI", 55)
        self.min_senti = min_senti if min_senti is not None else _env_float("STRAT_SENTI_MIN", 0.10)
        self.cooldown = cooldown if cooldown is not None else _env_int("STRAT_COOLDOWN_SEC", 300)
        self.max_pos_per_symbol = (
            max_pos_per_symbol
            if max_pos_per_symbol is not None
            else _env_int("STRAT_MAX_POS_PER_SYMBOL", 1)
        )
        self.disable_in_choppy = _env_bool("STRAT_REGIME_DISABLE_CHOPPY", True)
        self._time = time_fn or time.time
        self.last_trade_ts: dict[str, float] = {}
        self.open_positions: dict[str, int] = {}

    def on_bar(
        self, symbol: str, bar: Bar, senti: Optional[float], regime: str
    ) -> Optional[OrderPlan]:
        """Generate an order plan for an equity symbol if conditions are met."""

        if self.disable_in_choppy and regime == "choppy":
            return None

        now = self._time()
        last_ts = self.last_trade_ts.get(symbol, 0.0)
        if now - last_ts < self.cooldown:
            return None

        if self.open_positions.get(symbol, 0) >= self.max_pos_per_symbol:
            return None

        rsi_value = self.rsi.update(bar.close)
        orb_state = self.orb.update(bar.high, bar.low)
        if rsi_value is None or orb_state.get("active", True):
            return None

        if senti is None or senti < self.min_senti:
            return None

        if rsi_value < self.min_rsi:
            return None

        breakout = self.orb.breakout(bar.close)
        if breakout == 1:
            self.last_trade_ts[symbol] = now
            self.open_positions[symbol] = self.open_positions.get(symbol, 0) + 1
            return OrderPlan(
                symbol=symbol,
                side="buy",
                qty=10,
                limit_price=bar.close,
                asset_class="equity",
                note="ORB+momentum",
            )
        return None

    def on_fill(self, symbol: str) -> None:
        if symbol in self.open_positions:
            self.open_positions[symbol] = max(0, self.open_positions[symbol] - 1)

    def on_flatten(self, symbol: str) -> None:
        self.open_positions[symbol] = 0
