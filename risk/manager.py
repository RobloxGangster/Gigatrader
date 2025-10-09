"""Risk management engine."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict

from core.interfaces import Decision, RiskManager
from core.kill_switch import KillSwitch

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RiskState:
    daily_pnl: float = 0.0
    open_positions: int = 0
    exposure: float = 0.0


class ConfiguredRiskManager(RiskManager):
    """Risk manager enforcing global and options-specific caps."""

    def __init__(self, config: Dict[str, float], kill_switch: KillSwitch) -> None:
        self._config = config
        self._kill_switch = kill_switch

    async def pre_trade_check(self, order: Dict, portfolio: Dict) -> Decision:
        if await self._kill_switch.engaged():
            return Decision(False, "Kill switch engaged")

        if portfolio["daily_loss"] <= -abs(self._config["daily_loss_limit"]):
            return Decision(False, "Daily loss limit breached")

        if abs(order.get("notional", 0.0)) > self._config["max_exposure"]:
            return Decision(False, "Exposure limit exceeded")

        if portfolio["open_positions"] >= self._config["max_positions"]:
            return Decision(False, "Max open positions reached")

        if order.get("asset_class") == "option":
            if order.get("notional", 0.0) > self._config["options_max_notional_per_expiry"]:
                return Decision(False, "Option notional limit exceeded")
            greeks = order.get("greeks", {})
            delta = greeks.get("delta", 0.0)
            if not (self._config["delta_bounds"][0] <= abs(delta) <= self._config["delta_bounds"][1]):
                return Decision(False, "Delta outside bounds")
            if abs(greeks.get("vega", 0.0)) > self._config["vega_limit"]:
                return Decision(False, "Vega limit exceeded")
            if abs(greeks.get("theta", 0.0)) > self._config["theta_limit"]:
                return Decision(False, "Theta limit exceeded")
            if order.get("liquidity", 0) < self._config["min_option_liquidity"]:
                return Decision(False, "Insufficient option liquidity")

        return Decision(True)

    async def size(self, order_context: Dict) -> float:
        risk_budget = self._config["per_trade_loss_limit"]
        atr = order_context.get("atr", 1.0)
        if atr <= 0:
            logger.warning("ATR non-positive; falling back to minimum size")
            return 0.0
        return max(risk_budget / atr, 0.0)
