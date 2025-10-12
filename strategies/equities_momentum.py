"""Equities intraday momentum strategy scaffold."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List

from core.interfaces import Strategy

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MomentumState:
    universe: List[str]
    atr: Dict[str, float]
    regime: str = "neutral"


class EquitiesMomentumStrategy(Strategy):
    """Combines momentum, z-score and opening range breakout signals."""

    def __init__(self, universe: List[str]) -> None:
        self.state = MomentumState(universe=universe, atr={})

    async def prepare(self, data_context: Dict) -> None:
        logger.info(
            "Preparing equities momentum strategy", extra={"_extra_universe": self.state.universe}
        )
        self.state.atr = data_context.get("atr", {})
        self.state.regime = data_context.get("regime", "neutral")

    async def on_bar(self, event: Dict) -> List[Dict]:
        symbol = event["symbol"]
        signals = event.get("signals", {})
        if self.state.regime == "halted":
            return []
        if not signals.get("orb_breakout"):
            return []
        logger.debug("Generating order", extra={"_extra_symbol": symbol})
        return [
            {
                "symbol": symbol,
                "side": "buy" if signals["momentum"] > 0 else "sell",
                "asset_class": "us_equity",
                "type": "limit",
                "qty": signals.get("size", 0),
                "time_in_force": "day",
                "order_class": "bracket",
                "take_profit": {"limit_price": signals.get("target")},
                "stop_loss": {"stop_price": signals.get("stop")},
            }
        ]

    async def on_fill(self, event: Dict) -> None:
        logger.info("Order filled", extra={"_extra_fill": event})
