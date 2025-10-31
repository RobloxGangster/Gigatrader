"""Top-level orchestration for the strategy layer."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

from backend.services.orchestrator import record_decision_cycle
from core.market_hours import market_is_open, seconds_until_open
from services.execution.engine import ExecutionEngine
from services.execution.types import ExecIntent
from services.gateway.options import OptionGateway
from services.risk.state import StateProvider
from services.strategy.equities import EquityStrategy
from services.strategy.options_strat import OptionStrategy
from services.strategy.regime import RegimeDetector
from services.strategy.types import Bar, OrderPlan
from services.strategy.universe import Universe


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


class StrategyEngine:
    """Coordinates universe selection, regime detection, and strategy routing."""

    def __init__(
        self,
        exec_engine: ExecutionEngine,
        option_gateway: OptionGateway,
        state: StateProvider,
        *,
        universe: Optional[Universe] = None,
        equity_strategies: Optional[Iterable[EquityStrategy]] = None,
        option_strategies: Optional[Iterable[OptionStrategy]] = None,
        regime_detector: Optional[RegimeDetector] = None,
    ) -> None:
        self.exec = exec_engine
        self.option_gateway = option_gateway
        self.state = state
        self.regime = regime_detector or RegimeDetector()
        base_symbols_env = os.getenv("SYMBOLS", "")
        base_symbols = [sym.strip() for sym in base_symbols_env.split(",") if sym.strip()]
        max_watch = _env_int("STRAT_UNIVERSE_MAX", 25)
        self.universe = universe or Universe(base_symbols, max_watch=max_watch)
        self._equity_enabled = _env_bool("STRAT_EQUITY_ENABLED", True)
        self._option_enabled = _env_bool("STRAT_OPTION_ENABLED", True)
        self._senti_min = float(os.getenv("STRAT_SENTI_MIN", "0") or 0)
        self.equity_strategies: List[EquityStrategy] = list(equity_strategies or [EquityStrategy()])
        self.option_strategies: List[OptionStrategy] = list(option_strategies or [OptionStrategy()])
        self.latest_sentiment: Dict[str, float] = {}
        self.allow_preopen = _env_bool("ALLOW_PREOPEN", True)
        self.preopen_minutes = _env_int("PREOPEN_PLACE_MINUTES", 5)
        self.default_open_kind = (
            os.getenv("DEFAULT_OPEN_ORDER_KIND", "market").strip().lower() or "market"
        )

    def register_equity_strategy(self, strategy: EquityStrategy) -> None:
        self.equity_strategies.append(strategy)

    def register_option_strategy(self, strategy: OptionStrategy) -> None:
        self.option_strategies.append(strategy)

    async def on_bar(self, symbol: str, bar: Bar, senti: Optional[float]) -> None:
        normalized_symbol = symbol.upper()
        if senti is not None:
            self.latest_sentiment[normalized_symbol] = senti
            self.universe.update_with_sentiment({normalized_symbol: senti})
        else:
            senti = self.latest_sentiment.get(normalized_symbol)

        if not self.universe.contains(normalized_symbol):
            return

        regime = self.regime.update(bar.high, bar.low, bar.close)

        if self._senti_min > 0:
            senti_mag = abs(senti) if senti is not None else None
            if senti_mag is None or senti_mag < self._senti_min:
                return

        total_signals = 0
        orders_submitted = 0
        preopen_orders = 0
        now = datetime.now(timezone.utc)
        market_open = market_is_open(now)
        will_trade_at_open = False
        seconds_to_open = seconds_until_open(now)
        preopen_window = max(0, self.preopen_minutes) * 60
        if (
            not market_open
            and self.allow_preopen
            and seconds_to_open > 0
            and seconds_to_open <= preopen_window
        ):
            will_trade_at_open = True

        if self._equity_enabled:
            for strategy in self.equity_strategies:
                plan = strategy.on_bar(normalized_symbol, bar, senti, regime)
                if plan is None:
                    continue
                total_signals += 1
                tif, order_type = self._resolve_order_params(
                    market_open=market_open,
                    will_trade_at_open=will_trade_at_open,
                    plan=plan,
                )
                if will_trade_at_open and not market_open:
                    preopen_orders += 1
                await self._route_equity_plan(
                    plan,
                    time_in_force=tif,
                    order_type=order_type,
                )
                orders_submitted += 1

        if self._option_enabled:
            for strategy in self.option_strategies:
                plan = strategy.on_bar(normalized_symbol, bar, senti, regime)
                if plan is None:
                    continue
                total_signals += 1
                await self._route_option_plan(plan)
                orders_submitted += 1

        record_decision_cycle(
            will_trade_at_open=will_trade_at_open,
            signals=total_signals,
            orders=orders_submitted,
            preopen_queue=preopen_orders,
        )

    def _resolve_order_params(
        self,
        *,
        market_open: bool,
        will_trade_at_open: bool,
        plan: OrderPlan,
    ) -> tuple[str | None, str | None]:
        if market_open or not will_trade_at_open:
            return None, None
        tif = "opg"
        order_type = None
        if plan.limit_price is not None:
            order_type = "limit"
        elif self.default_open_kind == "limit":
            if plan.limit_price is not None:
                order_type = "limit"
            else:
                order_type = "market"
        else:
            order_type = "market"
        return tif, order_type

    async def _route_equity_plan(
        self,
        plan: OrderPlan,
        *,
        time_in_force: str | None = None,
        order_type: str | None = None,
    ) -> None:
        side = "buy" if str(plan.side).lower() == "buy" else "sell"
        intent = ExecIntent(
            symbol=plan.symbol,
            side=side,
            qty=plan.qty,
            limit_price=plan.limit_price,
            asset_class="equity",
            client_tag=f"eq:{plan.note}" if plan.note else "eq:auto",
            take_profit_pct=plan.take_profit_pct,
            stop_loss_pct=plan.stop_loss_pct,
            time_in_force=time_in_force,
            order_type=order_type,
        )
        await self.exec.submit(intent)

    async def _route_option_plan(self, plan: OrderPlan) -> None:
        side = "buy" if str(plan.side).lower() == "buy" else "sell"
        await self.option_gateway.propose_option_trade(plan.symbol, side, plan.qty)
