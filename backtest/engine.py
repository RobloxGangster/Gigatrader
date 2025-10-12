"""Event-driven backtest engine."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Dict, Iterable, List

from core.interfaces import SlippageCostModel, Strategy

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BacktestResult:
    equity_curve: List[float]
    trades: List[Dict]
    metrics: Dict[str, float]


@dataclass(slots=True)
class BacktestConfig:
    latency_ms: int = 50
    partial_fill_probability: float = 0.1
    slippage_model: SlippageCostModel | None = None


class BacktestEngine:
    """Drives strategies over historical data and simulates fills."""

    def __init__(self, strategies: Iterable[Strategy], config: BacktestConfig) -> None:
        self._strategies = list(strategies)
        self._config = config

    async def run(self, bars: Iterable[Dict]) -> BacktestResult:
        trades: List[Dict] = []
        equity_curve: List[float] = [0.0]
        for strategy in self._strategies:
            await strategy.prepare({})
        for bar in bars:
            orders: List[Dict] = []
            for strategy in self._strategies:
                proposed = await strategy.on_bar(bar)
                orders.extend(proposed)
            fills = await self._simulate_fills(orders, bar)
            trades.extend(fills)
            equity_curve.append(equity_curve[-1] + sum(fill.get("pnl", 0.0) for fill in fills))
        metrics = {"CAGR": 0.0, "Sharpe": 0.0}
        return BacktestResult(equity_curve=equity_curve, trades=trades, metrics=metrics)

    async def _simulate_fills(self, orders: List[Dict], bar: Dict) -> List[Dict]:
        results: List[Dict] = []
        for order in orders:
            await asyncio.sleep(self._config.latency_ms / 1000)
            fill_price = bar.get("close")
            qty = order.get("qty", 0)
            pnl = (bar.get("close", 0.0) - order.get("limit_price", bar.get("close", 0.0))) * qty
            results.append({"order": order, "fill_price": fill_price, "qty": qty, "pnl": pnl})
        return results
