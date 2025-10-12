"""Options strategy implementations for the strategy engine."""

from __future__ import annotations

import os
import time
from typing import Callable, Optional

from services.strategy.types import Bar, OrderPlan


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


class OptionStrategy:
    """Directional options strategy that routes trades through the option gateway."""

    def __init__(
        self,
        *,
        min_senti: Optional[float] = None,
        cooldown: Optional[int] = None,
        min_volume: Optional[float] = None,
        time_fn: Optional[Callable[[], float]] = None,
    ) -> None:
        self.min_senti = min_senti if min_senti is not None else _env_float("STRAT_SENTI_MIN", 0.10)
        self.cooldown = cooldown if cooldown is not None else _env_int("STRAT_COOLDOWN_SEC", 300)
        self.min_volume = (
            min_volume if min_volume is not None else _env_float("STRAT_OPTION_MIN_VOLUME", 50000)
        )
        self.disable_in_choppy = _env_bool("STRAT_REGIME_DISABLE_CHOPPY", True)
        self._time = time_fn or time.time
        self.last_trade_ts: dict[str, float] = {}

    def on_bar(
        self, symbol: str, bar: Bar, senti: Optional[float], regime: str
    ) -> Optional[OrderPlan]:
        """Generate an order plan for options tied to the given underlying."""

        if self.disable_in_choppy and regime == "choppy":
            return None

        if senti is None or senti < self.min_senti:
            return None

        if bar.volume < self.min_volume:
            return None

        now = self._time()
        last_ts = self.last_trade_ts.get(symbol, 0.0)
        if now - last_ts < self.cooldown:
            return None

        if bar.close == bar.open:
            return None

        side = "buy" if bar.close > bar.open else "sell"
        note = "Directional call" if side == "buy" else "Directional put"

        self.last_trade_ts[symbol] = now
        return OrderPlan(symbol=symbol, side=side, qty=1, asset_class="option", note=note)
