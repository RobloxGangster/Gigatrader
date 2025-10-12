"""Options directional and debit spread strategy scaffold."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List

from core.interfaces import Strategy

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class OptionsState:
    target_delta: tuple[float, float]
    regime: str = "neutral"


class OptionsDirectionalStrategy(Strategy):
    """Selects directional options or debit spreads based on trend signals."""

    def __init__(self, target_delta: tuple[float, float]) -> None:
        self.state = OptionsState(target_delta=target_delta)

    async def prepare(self, data_context: Dict) -> None:
        self.state.regime = data_context.get("regime", "neutral")

    async def on_bar(self, event: Dict) -> List[Dict]:
        if self.state.regime == "halted":
            return []
        chain = event.get("option_chain")
        if not chain:
            logger.warning("Missing option chain; skipping trade")
            return []
        best = _select_contract(chain, self.state.target_delta)
        if not best:
            return []
        return [best]

    async def on_fill(self, event: Dict) -> None:
        logger.info("Options fill", extra={"_extra_fill": event})


def _select_contract(chain: List[Dict], delta_range: tuple[float, float]) -> Dict | None:
    """Pick the first contract meeting delta and liquidity criteria."""

    low, high = delta_range
    for contract in chain:
        greeks = contract.get("greeks", {})
        delta = abs(greeks.get("delta", 0.0))
        if low <= delta <= high and contract.get("volume", 0) > 0:
            return {
                "symbol": contract["symbol"],
                "asset_class": "option",
                "type": "limit",
                "qty": contract.get("size", 1),
                "limit_price": contract.get("mid"),
                "notional": contract.get("mid", 0.0) * 100,
                "greeks": greeks,
                "liquidity": contract.get("volume", 0),
            }
    return None
