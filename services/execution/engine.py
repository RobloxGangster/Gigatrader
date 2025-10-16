"""Execution engine bridging intents, risk checks, and Alpaca orders."""

from __future__ import annotations

import asyncio
import math
import os
import uuid
from typing import Any, Dict, Optional

from services.execution.adapter_alpaca import AlpacaAdapter
from services.execution.types import ExecIntent, ExecResult
from services.execution.updates import UpdateBus
from services.risk.engine import Proposal, RiskManager
from services.risk.state import Position, StateProvider
from services.telemetry import metrics


def _bracket_prices(side: str, px: float, tp_pct: float, sl_pct: float) -> tuple[float, float]:
    direction = 1.0 if side == "buy" else -1.0
    tp = px * (1.0 + direction * tp_pct / 100.0)
    sl = px * (1.0 - direction * sl_pct / 100.0)
    return (round(tp, 2), round(sl, 2))


def _parse_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


class ExecutionEngine:
    """Asynchronous execution coordinator for Alpaca paper trading."""

    def __init__(
        self,
        *,
        risk: RiskManager,
        state: StateProvider,
        adapter: Optional[AlpacaAdapter] = None,
        updates: Optional[UpdateBus] = None,
    ) -> None:
        self.risk = risk
        self.state = state
        self.adapter = adapter or AlpacaAdapter()
        self.updates = updates or UpdateBus()
        self.default_tp = float(os.getenv("DEFAULT_TP_PCT", "1.0"))
        self.default_sl = float(os.getenv("DEFAULT_SL_PCT", "0.5"))
        self._intent_lock = asyncio.Lock()
        self._seen_intents: dict[str, str] = {}
        self._orders: dict[str, Dict[str, Any]] = {}
        self._order_fill_qty: dict[str, float] = {}

    async def run_update_loop(self) -> None:
        """Run the update bus, feeding normalized updates into the state provider."""

        async def _handler(update: Dict[str, Any]) -> None:
            await self.process_update(update)

        await self.updates.run(_handler)

    def _intent_key(self, intent: ExecIntent) -> str:
        return intent.idempotency_key()

    def _intent_to_payload(self, intent: ExecIntent, client_order_id: str) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "symbol": intent.symbol,
            "side": intent.submit_side or intent.side,
            "qty": intent.qty,
            "limit_price": intent.limit_price,
            "client_order_id": client_order_id,
            "asset_class": intent.asset_class,
        }
        if intent.asset_class == "option" and intent.option_symbol:
            payload["symbol"] = intent.option_symbol
            payload["underlying_symbol"] = intent.symbol

        if intent.asset_class == "equity":
            limit_price = intent.limit_price
            tp_pct = (
                intent.take_profit_pct if intent.take_profit_pct is not None else self.default_tp
            )
            sl_pct = intent.stop_loss_pct if intent.stop_loss_pct is not None else self.default_sl
            if limit_price is not None and tp_pct > 0 and sl_pct > 0:
                tp, sl = _bracket_prices(intent.side, limit_price, tp_pct, sl_pct)
                payload["take_profit"] = {"limit_price": tp}
                payload["stop_loss"] = {"stop_price": sl}
        return payload

    async def submit(self, intent: ExecIntent) -> ExecResult:
        """Submit a validated intent after re-running risk checks."""

        key = self._intent_key(intent)
        async with self._intent_lock:
            existing = self._seen_intents.get(key)
            if existing is not None:
                metrics.inc_order_reject("duplicate_intent")
                return ExecResult(False, "duplicate_intent", existing)
            client_order_id = intent.client_tag or str(uuid.uuid4())
            # Pre-populate with the generated client order id so in-flight duplicates see it.
            self._seen_intents[key] = client_order_id
        proposal = Proposal(
            symbol=intent.symbol,
            side=intent.side,
            qty=intent.qty,
            price=intent.limit_price or 0.0,
            is_option=intent.asset_class == "option",
        )
        decision = self.risk.pre_trade_check(proposal)
        if not decision.allow:
            metrics.inc_order_reject(f"risk_denied_{decision.reason or 'unknown'}")
            async with self._intent_lock:
                self._seen_intents.pop(key, None)
            return ExecResult(False, f"risk_denied:{decision.reason}", client_order_id)

        payload = self._intent_to_payload(intent, client_order_id)
        try:
            response = await self.adapter.submit_order(payload)
        except Exception as exc:  # pragma: no cover - network errors simulated in integration tests
            metrics.inc_order_reject(f"submit_failed_{exc.__class__.__name__}")
            async with self._intent_lock:
                self._seen_intents.pop(key, None)
            return ExecResult(False, f"submit_failed:{exc}", client_order_id)

        order_id: Optional[str]
        status: str
        if isinstance(response, dict):
            order_id = response.get("id") or response.get("order_id")
            status = response.get("status") or "unknown"
        else:
            order_id = getattr(response, "id", None) or getattr(response, "order_id", None)
            status = getattr(response, "status", None) or "unknown"
        alpaca_order_id = order_id or client_order_id
        async with self._intent_lock:
            self._seen_intents[key] = client_order_id
            self._orders[client_order_id] = {
                "alpaca_order_id": alpaca_order_id,
                "client_order_id": client_order_id,
                "intent": intent,
                "status": status,
                "symbol": intent.symbol,
                "side": intent.side,
                "qty": intent.qty,
            }
        if hasattr(self.state, "mark_trade"):
            timestamp = intent.meta.get("ts") if intent.meta else None
            try:
                self.state.mark_trade(intent.symbol, when=timestamp)
            except TypeError:
                self.state.mark_trade(intent.symbol)  # type: ignore[arg-type]
        return ExecResult(True, "accepted", client_order_id)

    async def cancel(self, client_order_id: str) -> bool:
        order = self._orders.get(client_order_id)
        if not order:
            return False
        try:
            await self.adapter.cancel_order(order["alpaca_order_id"])
            order["status"] = "canceled"
            return True
        except Exception:  # pragma: no cover - requires live API failures
            return False

    async def replace(
        self,
        client_order_id: str,
        *,
        qty: Optional[float] = None,
        limit_price: Optional[float] = None,
    ) -> bool:
        order = self._orders.get(client_order_id)
        if not order:
            return False
        payload: Dict[str, Any] = {}
        if qty is not None:
            payload["qty"] = qty
        if limit_price is not None:
            payload["limit_price"] = limit_price
        if not payload:
            return False
        try:
            await self.adapter.replace_order(order["alpaca_order_id"], payload)
            if limit_price is not None:
                order["intent"].limit_price = limit_price  # type: ignore[assignment]
            if qty is not None:
                order["intent"].qty = qty  # type: ignore[assignment]
            return True
        except Exception:  # pragma: no cover
            return False

    async def process_update(self, update: Dict[str, Any]) -> None:
        """Process a trading update (fill/partial/cancel) and reconcile state."""

        order_data = update.get("order", update)
        client_order_id = order_data.get("client_order_id")
        order_id = order_data.get("id")
        status = (order_data.get("status") or update.get("event") or "").lower()
        symbol = order_data.get("symbol") or order_data.get("asset_symbol")
        side = (order_data.get("side") or "").lower()
        fill_price = _parse_float(
            order_data.get("fill_price")
            or order_data.get("filled_avg_price")
            or update.get("fill_price")
        )
        realized_pl = _parse_float(update.get("realized_pl") or order_data.get("realized_pl"))
        timestamp_raw = update.get("timestamp") or order_data.get("filled_at")
        asset_class = (order_data.get("asset_class") or update.get("asset_class") or "").lower()
        filled_qty_total = _parse_float(
            order_data.get("filled_qty") or order_data.get("filled_quantity")
        )
        fill_qty_delta = _parse_float(order_data.get("fill_qty") or order_data.get("fill_quantity"))
        if fill_qty_delta <= 0 and filled_qty_total > 0:
            prev = 0.0
            if order_id:
                prev = self._order_fill_qty.get(order_id, 0.0)
            fill_qty_delta = max(0.0, filled_qty_total - prev)
        if order_id:
            self._order_fill_qty[order_id] = (
                self._order_fill_qty.get(order_id, 0.0) + fill_qty_delta
            )

        if client_order_id and client_order_id in self._orders:
            self._orders[client_order_id]["status"] = status or self._orders[client_order_id].get(
                "status", ""
            )
        if status in {"canceled", "rejected"}:
            return

        if not symbol or fill_qty_delta <= 0 or fill_price <= 0:
            return

        direction = 1.0 if side == "buy" else -1.0
        qty_delta = direction * fill_qty_delta
        timestamp = _parse_float(timestamp_raw)

        existing = None
        if hasattr(self.state, "positions"):
            existing = self.state.positions.get(symbol)  # type: ignore[attr-defined]
        prev_qty = existing.qty if existing else 0.0
        prev_notional = existing.notional if existing else 0.0

        new_qty = prev_qty + qty_delta
        new_notional = new_qty * fill_price
        if hasattr(self.state, "positions"):
            if math.isclose(new_qty, 0.0, abs_tol=1e-9):
                self.state.positions.pop(symbol, None)  # type: ignore[attr-defined]
            else:
                self.state.positions[symbol] = Position(
                    symbol=symbol,
                    qty=new_qty,
                    notional=new_notional,
                    is_option=asset_class == "option",
                )  # type: ignore[attr-defined]
        if hasattr(self.state, "portfolio_notional"):
            self.state.portfolio_notional = (
                self.state.portfolio_notional  # type: ignore[attr-defined]
                - abs(prev_notional)
                + abs(new_notional)
            )
        if hasattr(self.state, "day_pnl") and realized_pl:
            self.state.day_pnl += realized_pl  # type: ignore[attr-defined]
        if hasattr(self.state, "mark_trade"):
            when = timestamp if timestamp > 0 else None
            try:
                self.state.mark_trade(symbol, when=when)
            except TypeError:
                self.state.mark_trade(symbol)  # type: ignore[arg-type]

    def clear_intent_cache(self) -> None:
        """Clear idempotency cache (primarily for tests)."""

        self._seen_intents.clear()
