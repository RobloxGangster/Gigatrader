"""Top-level orchestration for the strategy layer."""

from __future__ import annotations

import asyncio
import logging
import math
import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from backend.services.orchestrator import queue_preopen_intent, record_decision_cycle
from core.market_hours import market_is_open, seconds_until_open
from backend.config.extended_universe import (
    is_extended as is_extended_session,
    is_rth as is_rth_session,
    load_extended_tickers,
)
from backend.services.universe_registry import get_override_universe
from services.execution.engine import ExecutionEngine
from services.execution.preopen_queue import PreopenIntent
from services.execution.types import ExecIntent
from services.gateway.options import OptionGateway
from services.risk.state import Position, StateProvider
from services.strategy.equities import EquityStrategy
from services.strategy.options_strat import OptionStrategy
from services.strategy.regime import RegimeDetector
from services.strategy.types import Bar, OrderPlan
from services.strategy.universe import Universe


FALLBACK_UNIVERSE = ["AAPL", "MSFT", "NVDA", "SPY"]


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


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
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
        self.log = logging.getLogger("gigatrader.strategy.engine")
        self.exec = exec_engine
        self.option_gateway = option_gateway
        self.state = state
        self.regime = regime_detector or RegimeDetector()
        base_symbols_env = os.getenv("SYMBOLS", "")
        base_symbols = [sym.strip() for sym in base_symbols_env.split(",") if sym.strip()]
        if not base_symbols:
            base_symbols = list(FALLBACK_UNIVERSE)
        max_watch = _env_int("STRAT_UNIVERSE_MAX", 25)
        self.universe = universe or Universe(base_symbols, max_watch=max_watch)
        self._extended_universe: List[str] = load_extended_tickers()
        self._extended_set = {sym.upper() for sym in self._extended_universe}
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
        self.enable_dynamic_sizing = _env_bool("ENABLE_DYNAMIC_SIZING", False)
        self.per_trade_risk_pct = _env_float("PER_TRADE_RISK_PCT", 1.0)
        self.enable_trailing = _env_bool("ENABLE_TRAILING", False)
        self.trailing_be_pct = _env_float("TRAIL_BE_PCT", 0.5)
        self.trailing_step_pct = max(0.0, _env_float("TRAIL_STEP_PCT", 0.25))
        self.default_stop_pct = abs(_env_float("DEFAULT_SL_PCT", 0.5))
        self.default_tp_pct = abs(_env_float("DEFAULT_TP_PCT", 1.0))
        self.max_symbol_notional = abs(
            _env_float("MAX_SYMBOL_NOTIONAL", _env_float("MAX_PORTFOLIO_NOTIONAL", 0.0))
        )
        self._trailing_state: Dict[str, Dict[str, float | bool]] = {}

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

        now = datetime.now(timezone.utc)
        extended_now = is_extended_session(now)
        rth_now = is_rth_session(now)

        override_universe = get_override_universe()
        base_universe = self.universe.get()
        if not base_universe:
            base_universe = list(FALLBACK_UNIVERSE)

        if override_universe:
            active_universe = override_universe
        elif not rth_now and self._extended_universe:
            active_universe = self._extended_universe
        else:
            active_universe = base_universe

        active_set = {sym.strip().upper() for sym in active_universe if sym}
        if normalized_symbol not in active_set:
            return

        if not override_universe and not self.universe.contains(normalized_symbol):
            return

        regime = self.regime.update(bar.high, bar.low, bar.close)

        if self._senti_min > 0:
            senti_mag = abs(senti) if senti is not None else None
            if senti_mag is None or senti_mag < self._senti_min:
                return

        total_signals = 0
        orders_submitted = 0
        preopen_orders = 0
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

        positions: Dict[str, Position] = {}
        if self.enable_trailing:
            try:
                positions = self.state.get_positions()
            except NotImplementedError:
                positions = {}
            await self._handle_trailing(normalized_symbol, bar.close, positions)

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
                extended_for_order = extended_now and not will_trade_at_open
                try:
                    submitted = await self._route_equity_plan(
                        plan,
                        market_open=market_open,
                        time_in_force=tif,
                        order_type=order_type,
                        current_price=bar.close,
                        extended_hours=extended_for_order,
                    )
                except ValueError as exc:
                    self.log.warning(
                        "strategy.order_rejected",
                        extra={
                            "symbol": normalized_symbol,
                            "reason": str(exc),
                            "extended_hours": extended_for_order,
                        },
                    )
                    continue
                if submitted:
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
        market_open: bool,
        time_in_force: str | None = None,
        order_type: str | None = None,
        current_price: float = 0.0,
        extended_hours: bool = False,
    ) -> bool:
        side = "buy" if str(plan.side).lower() == "buy" else "sell"
        tif_value = (time_in_force or "").lower() if time_in_force else None
        order_kind = order_type or ("limit" if plan.limit_price is not None else "market")
        entry_price = plan.limit_price if plan.limit_price is not None else current_price
        if extended_hours:
            if plan.limit_price is None:
                raise ValueError("Extended-hours orders require a limit price")
            tif_value = "day"
            order_kind = "limit"
        stop_pct = abs(plan.stop_loss_pct) if plan.stop_loss_pct is not None else self.default_stop_pct
        take_pct = abs(plan.take_profit_pct) if plan.take_profit_pct is not None else self.default_tp_pct
        qty = max(1, int(round(plan.qty)))
        if self.enable_dynamic_sizing:
            qty = self._dynamic_quantity(entry_price, stop_pct, fallback_qty=qty)
        plan.stop_loss_pct = stop_pct
        plan.take_profit_pct = take_pct
        if self.enable_trailing:
            self._arm_trailing(plan.symbol, 1 if side == "buy" else -1, entry_price, stop_pct)

        if tif_value == "opg" and not market_open:
            preopen_intent = PreopenIntent(
                symbol=plan.symbol,
                side=side,
                qty=qty,
                order_kind=order_kind,
                limit_price=plan.limit_price,
            )
            await queue_preopen_intent(preopen_intent)
            return False

        intent_meta: Dict[str, Any] = {}
        if extended_hours:
            intent_meta["extended_hours"] = True

        resolved_tif = tif_value if tif_value else None
        resolved_order_type = order_kind if (order_type is not None or extended_hours) else None

        intent = ExecIntent(
            symbol=plan.symbol,
            side=side,
            qty=float(qty),
            limit_price=plan.limit_price,
            asset_class="equity",
            client_tag=f"eq:{plan.note}" if plan.note else "eq:auto",
            take_profit_pct=take_pct,
            stop_loss_pct=stop_pct,
            time_in_force=resolved_tif or time_in_force,
            order_type=resolved_order_type,
            meta=intent_meta,
        )
        await self.exec.submit(intent)
        return True

    def _dynamic_quantity(self, entry_price: float, stop_pct: float, *, fallback_qty: int) -> int:
        if entry_price <= 0 or stop_pct <= 0:
            return fallback_qty
        equity = None
        try:
            equity = self.state.get_account_equity()
        except Exception:
            equity = None
        if equity is None or equity <= 0:
            return fallback_qty
        per_trade_risk = max(0.0, self.per_trade_risk_pct) / 100.0 * equity
        per_share_risk = entry_price * (stop_pct / 100.0)
        if per_share_risk <= 0:
            return fallback_qty
        qty = math.floor(per_trade_risk / per_share_risk)
        if qty <= 0:
            qty = 1
        max_notional = self.max_symbol_notional
        if max_notional > 0:
            qty = min(qty, int(max_notional // entry_price) if entry_price > 0 else qty)
        return max(1, qty)

    def _arm_trailing(
        self,
        symbol: str,
        direction: int,
        entry_price: float,
        stop_pct: float,
    ) -> None:
        if not self.enable_trailing or entry_price <= 0 or stop_pct <= 0:
            return
        base_stop = -abs(stop_pct) if direction > 0 else abs(stop_pct)
        self._trailing_state[symbol] = {
            "direction": float(direction),
            "entry": float(entry_price),
            "last_stop_pct": float(base_stop),
            "breakeven": False,
            "exiting": False,
        }

    async def _handle_trailing(
        self,
        symbol: str,
        price: float,
        positions: Dict[str, Position],
    ) -> None:
        state = self._trailing_state.get(symbol)
        position = positions.get(symbol)
        if position is None or math.isclose(position.qty, 0.0, abs_tol=1e-9):
            if state is not None:
                self._trailing_state.pop(symbol, None)
            return
        direction = 1.0 if position.qty > 0 else -1.0
        entry_price = self._position_entry_price(position)
        if entry_price <= 0 or price <= 0:
            return
        if state is None:
            self._arm_trailing(symbol, int(direction), entry_price, self.default_stop_pct)
            state = self._trailing_state.get(symbol)
            if state is None:
                return
        if float(state.get("direction", direction)) != direction:
            self._arm_trailing(symbol, int(direction), entry_price, self.default_stop_pct)
            state = self._trailing_state.get(symbol)
            if state is None:
                return
        state["entry"] = entry_price
        stop_pct = float(state.get("last_stop_pct", -self.default_stop_pct))
        breakeven = bool(state.get("breakeven", False))
        gain_pct = (price - entry_price) / entry_price * 100.0 * direction
        if not breakeven and gain_pct >= self.trailing_be_pct:
            breakeven = True
            stop_pct = 0.0
        if breakeven:
            extra = gain_pct - self.trailing_be_pct
            if extra >= self.trailing_step_pct > 0:
                steps = math.floor(extra / self.trailing_step_pct)
                target_pct = self.trailing_be_pct + max(0, steps - 1) * self.trailing_step_pct
                target_pct = max(0.0, target_pct)
                if target_pct > stop_pct:
                    stop_pct = target_pct
        state["breakeven"] = breakeven
        state["last_stop_pct"] = stop_pct
        stop_price = entry_price * (1.0 + direction * stop_pct / 100.0)
        exiting = bool(state.get("exiting", False))
        should_exit = (direction > 0 and price <= stop_price) or (
            direction < 0 and price >= stop_price
        )
        if should_exit and not exiting:
            await self._submit_trailing_exit(symbol, position, direction)
            state["exiting"] = True
        elif not should_exit:
            state["exiting"] = False

    async def _submit_trailing_exit(
        self,
        symbol: str,
        position: Position,
        direction: float,
    ) -> None:
        qty = abs(float(position.qty))
        if qty <= 0:
            return
        side = "sell" if direction > 0 else "buy"
        intent = ExecIntent(
            symbol=symbol,
            side=side,
            qty=qty,
            asset_class="equity",
            order_type="market",
            client_tag=f"trail-exit:{symbol.lower()}",
        )
        attempts = 0
        while attempts < 2:
            try:
                result = await self.exec.submit(intent)
            except asyncio.CancelledError:
                raise
            except Exception:
                attempts += 1
                if attempts >= 2:
                    break
                await asyncio.sleep(0.5)
                continue
            if result.accepted:
                break
            attempts += 1
            if attempts >= 2:
                break
            await asyncio.sleep(0.25)

    @staticmethod
    def _position_entry_price(position: Position) -> float:
        qty = abs(float(position.qty))
        if qty <= 1e-9:
            return 0.0
        try:
            return abs(float(position.notional)) / qty
        except (TypeError, ValueError):
            return 0.0

    async def _route_option_plan(self, plan: OrderPlan) -> None:
        side = "buy" if str(plan.side).lower() == "buy" else "sell"
        await self.option_gateway.propose_option_trade(plan.symbol, side, plan.qty)
