"""Execution engine bridging intents, risk checks, and Alpaca orders."""

from __future__ import annotations

import asyncio
import logging
import math
import os
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional

from core.runtime_flags import get_runtime_flags

try:  # pragma: no cover - backend optional in pure services tests
    from backend.services.orchestrator import can_execute_trade, record_order_attempt
except Exception:  # pragma: no cover - fallback when backend unavailable
    def record_order_attempt(**_: Any) -> None:  # type: ignore[override]
        return None

    def can_execute_trade(
        flags: Any, kill_switch_engaged: bool, *, kill_reason: str | None = None
    ) -> tuple[bool, str | None]:
        if kill_switch_engaged or getattr(flags, "dry_run", False):
            return False, kill_reason or "execution_disabled"
        return True, None

from backend.utils.structlog import jlog
from services.execution.adapter_alpaca import AlpacaAdapter
from services.execution.types import ExecIntent, ExecResult
from services.execution.updates import UpdateBus
from services.risk.engine import Proposal, RiskManager
from services.risk.state import Position, StateProvider
from services.telemetry import metrics


EXECUTION_LOG_PATH = Path("logs/execution_debug.log")


def _ensure_debug_logger() -> logging.Logger:
    logger = logging.getLogger("gigatrader.execution.debug")
    if not getattr(logger, "_gigatrader_configured", False):  # type: ignore[attr-defined]
        logger.setLevel(logging.INFO)
        logger.propagate = False
        try:
            EXECUTION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        except Exception:  # pragma: no cover - filesystem guard
            pass
        marker_present = any(getattr(handler, "_gigatrader_marker", False) for handler in logger.handlers)
        if not marker_present:
            handler = RotatingFileHandler(
                EXECUTION_LOG_PATH,
                maxBytes=1_000_000,
                backupCount=5,
                encoding="utf-8",
            )
            handler._gigatrader_marker = True  # type: ignore[attr-defined]
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            logger.addHandler(handler)
        logger._gigatrader_configured = True  # type: ignore[attr-defined]
    return logger


EXEC_DEBUG_LOG = _ensure_debug_logger()


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
        self.log = logging.getLogger("gigatrader.execution")
        self.debug_log = EXEC_DEBUG_LOG
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
        if intent.time_in_force:
            payload["time_in_force"] = intent.time_in_force
        if intent.order_type:
            payload["type"] = intent.order_type
        if intent.meta.get("extended_hours"):
            payload["extended_hours"] = True
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
        if "type" not in payload:
            payload["type"] = "limit" if intent.limit_price is not None else "market"
        if "time_in_force" not in payload:
            payload["time_in_force"] = "day"
        return payload

    async def _forget_intent(self, key: str) -> None:
        async with self._intent_lock:
            self._seen_intents.pop(key, None)

    def _record_attempt(
        self,
        intent: ExecIntent,
        *,
        sent: bool,
        accepted: bool,
        reason: str,
    ) -> None:
        broker_impl = type(self.adapter).__name__ if self.adapter else "UnknownAdapter"
        try:
            record_order_attempt(
                symbol=intent.symbol,
                qty=intent.qty,
                side=intent.side,
                sent=sent,
                accepted=accepted,
                reason=reason,
                broker_impl=broker_impl,
            )
        except Exception:  # pragma: no cover - telemetry best effort
            pass
        try:
            self.debug_log.info(
                "execution.attempt",
                extra={
                    "symbol": intent.symbol,
                    "side": intent.side,
                    "qty": intent.qty,
                    "sent": sent,
                    "accepted": accepted,
                    "reason": reason,
                    "broker": broker_impl,
                    "dry_run": getattr(self.adapter, "dry_run", None),
                },
            )
        except Exception:  # pragma: no cover - logging guard
            pass

    async def submit(self, intent: ExecIntent) -> ExecResult:
        """Submit a validated intent after re-running risk checks."""

        key = self._intent_key(intent)
        async with self._intent_lock:
            existing = self._seen_intents.get(key)
            if existing is not None:
                metrics.inc_order_reject("duplicate_intent")
                result = ExecResult(
                    accepted=False,
                    reason="duplicate_intent",
                    client_order_id=existing,
                )
                self._record_attempt(intent, sent=False, accepted=False, reason=result.reason)
                self.log.info(
                    "execution.duplicate_intent",
                    extra={"symbol": intent.symbol, "side": intent.side, "qty": intent.qty},
                )
                return result
            client_order_id = intent.client_tag or str(uuid.uuid4())
            # Pre-populate with the generated client order id so in-flight duplicates see it.
            self._seen_intents[key] = client_order_id

        flags = get_runtime_flags()
        kill_switch_obj = getattr(self.risk, "kill_switch", None)
        kill_switch_engaged = False
        kill_reason = None
        if kill_switch_obj is not None:
            try:
                info = kill_switch_obj.info_sync()
                kill_switch_engaged = bool(info.get("engaged"))
                reason = info.get("reason")
                if isinstance(reason, str):
                    kill_reason = reason
            except Exception:  # pragma: no cover - defensive
                kill_switch_engaged = False
                kill_reason = None
        allowed, guard_reason = can_execute_trade(
            flags, kill_switch_engaged, kill_reason=kill_reason
        )
        if not allowed:
            await self._forget_intent(key)
            reason_code = guard_reason or "execution_guard"
            metrics.inc_order_reject(f"guard_{reason_code}")
            context = {
                "symbol": intent.symbol,
                "side": intent.side,
                "qty": intent.qty,
                "reason": reason_code,
            }
            self.log.info("execution.guard_block", extra=context)
            try:
                self.debug_log.info("execution.guard_block", extra=context)
            except Exception:  # pragma: no cover - logging guard
                pass
            try:
                jlog(
                    "trade.blocked",
                    symbol=intent.symbol,
                    reason=str(reason_code),
                    ctx="router.guard",
                )
            except Exception:  # pragma: no cover - logging guard
                self.log.debug("failed to emit trade.blocked guard", exc_info=True)
            result = ExecResult(
                accepted=False,
                reason=reason_code,
                client_order_id=client_order_id,
            )
            self._record_attempt(intent, sent=False, accepted=False, reason=result.reason)
            return result
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
            reason = f"risk_denied:{decision.reason}"
            context = {
                "symbol": intent.symbol,
                "side": intent.side,
                "qty": intent.qty,
                "reason": decision.reason,
            }
            self.log.info("execution.risk_denied", extra=context)
            try:
                self.debug_log.info("execution.risk_denied", extra=context)
            except Exception:  # pragma: no cover - logging guard
                pass
            try:
                jlog(
                    "trade.blocked",
                    symbol=intent.symbol,
                    reason=reason,
                    ctx="router.risk",
                )
            except Exception:  # pragma: no cover - logging guard
                self.log.debug("failed to emit trade.blocked risk", exc_info=True)
            result = ExecResult(
                accepted=False,
                reason=reason,
                client_order_id=client_order_id,
            )
            self._record_attempt(intent, sent=False, accepted=False, reason=result.reason)
            return result

        payload = self._intent_to_payload(intent, client_order_id)
        if isinstance(payload, dict):
            payload["client_order_id"] = client_order_id
        else:
            try:
                setattr(payload, "client_order_id", client_order_id)
            except Exception:
                pass
        try:
            jlog("trade.route", route="broker", payload=payload)
        except Exception:  # pragma: no cover - logging guard
            self.log.debug("failed to emit trade.route", exc_info=True)
        try:
            response = await self.adapter.submit_order(payload)
        except Exception as exc:  # pragma: no cover - network errors simulated in integration tests
            metrics.inc_order_reject(f"submit_failed_{exc.__class__.__name__}")
            async with self._intent_lock:
                self._seen_intents.pop(key, None)
            reason = f"submit_failed:{exc}"
            context = {
                "symbol": intent.symbol,
                "side": intent.side,
                "qty": intent.qty,
                "error": str(exc),
            }
            self.log.warning("execution.submit_failed", extra=context)
            try:
                self.debug_log.error("execution.submit_failed", extra=context)
            except Exception:  # pragma: no cover - logging guard
                pass
            try:
                jlog(
                    "trade.submit_error",
                    error=str(exc),
                    payload=payload,
                    symbol=intent.symbol,
                )
            except Exception:  # pragma: no cover - logging guard
                self.log.debug("failed to emit trade.submit_error", exc_info=True)
            result = ExecResult(
                accepted=False,
                reason=reason,
                client_order_id=client_order_id,
            )
            self._record_attempt(intent, sent=True, accepted=False, reason=result.reason)
            return result

        order_id: Optional[str] = None
        status: str = "pending"
        if isinstance(response, dict):
            order_id = response.get("id") or response.get("order_id")
            status = response.get("status") or status
        else:
            order_id = getattr(response, "id", None) or getattr(response, "order_id", None)
            status = getattr(response, "status", None) or status
        alpaca_order_id = order_id or client_order_id
        async with self._intent_lock:
            self._seen_intents[key] = client_order_id
            self._orders[client_order_id] = {
                "alpaca_order_id": alpaca_order_id,
                "order_id": order_id,
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
        result = ExecResult(
            accepted=True,
            reason="accepted",
            client_order_id=client_order_id,
            order_id=order_id,
        )
        self.log.info(
            "execution.submit_success",
            extra={
                "symbol": intent.symbol,
                "side": intent.side,
                "qty": intent.qty,
                "status": status,
                "order_id": order_id,
            },
        )
        try:
            self.debug_log.info(
                "execution.submit_success",
                extra={
                    "symbol": intent.symbol,
                    "side": intent.side,
                    "qty": intent.qty,
                    "status": status,
                    "order_id": order_id,
                },
            )
        except Exception:  # pragma: no cover - logging guard
            pass
        try:
            jlog(
                "trade.submitted",
                broker=getattr(self.adapter, "name", "alpaca"),
                client_order_id=client_order_id,
                id=order_id,
                status=status,
                symbol=intent.symbol,
                side=intent.side,
                qty=float(intent.qty),
            )
        except Exception:  # pragma: no cover - logging guard
            self.log.debug("failed to emit trade.submitted", exc_info=True)
        self._record_attempt(intent, sent=True, accepted=True, reason=status)
        return result

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
