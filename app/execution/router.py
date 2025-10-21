"""Order routing with risk controls and Alpaca submission."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import secrets
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Mapping, Optional, Sequence

from app.risk import Proposal, RiskManager
from app.state import ExecutionState
from core.config import get_order_defaults

from app.execution.audit import AuditLog
from app.oms.store import OmsStore, TERMINAL_STATES
from services.policy.gates import should_trade
from services.policy.sizing import size_position
from services.telemetry import metrics

from .alpaca_adapter import AlpacaAdapter, AlpacaOrderError, AlpacaUnauthorized

log = logging.getLogger("router")


@dataclass(slots=True)
class ExecIntent:
    """Normalized description of an order intent."""

    symbol: str
    side: str  # "buy" or "sell"
    qty: float
    limit_price: float
    bracket: bool = True
    asset_class: str = "equity"
    client_order_id: str | None = None
    meta: Dict[str, Any] | None = None


def _unique_cid(prefix: str | None = None) -> str:
    """Generate a short unique client_order_id under Alpaca's length limits."""

    p = (prefix or os.environ.get("ORDER_CLIENT_ID_PREFIX", "gt")).strip() or "gt"
    ts = time.strftime("%y%m%d%H%M%S", time.gmtime())
    rnd = secrets.token_hex(3)
    cid = f"{p}-{ts}-{rnd}"
    return cid[:48]


def _intent_key(intent: ExecIntent) -> str:
    payload = {
        "symbol": intent.symbol.upper(),
        "side": intent.side.lower(),
        "qty": float(intent.qty),
        "limit_price": round(float(intent.limit_price), 4),
        "asset_class": intent.asset_class.lower(),
        "bracket": bool(intent.bracket),
    }
    body = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


class OrderRouter:
    """Coordinates risk checks, idempotency and Alpaca order submission."""

    def __init__(
        self,
        risk: RiskManager,
        state: ExecutionState,
        *,
        store: OmsStore,
        audit: AuditLog,
        metrics: Optional[Any] = None,
        mock_mode: bool = False,
        adapter: Optional[AlpacaAdapter] = None,
    ) -> None:
        self.risk = risk
        self.state = state
        self.store = store
        self.audit = audit
        self.metrics = metrics
        self.mock_mode = mock_mode
        self.broker = adapter or AlpacaAdapter()

    # ------------------------------------------------------------------
    def _metrics_inc(self, key: str, value: int = 1) -> None:
        if self.metrics and hasattr(self.metrics, "increment"):
            try:
                self.metrics.increment(key, value)
            except Exception:  # pragma: no cover - defensive guard
                pass

    def _metrics_state(self, state: str) -> None:
        if self.metrics and hasattr(self.metrics, "note_state"):
            try:
                self.metrics.note_state(state)
            except Exception:  # pragma: no cover - defensive guard
                pass

    def _record_event(
        self,
        event: str,
        *,
        client_order_id: str,
        details: Dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "client_order_id": client_order_id,
        }
        if details:
            payload.update(details)
        self.audit.append(payload)

    def _record_transition(
        self,
        client_order_id: str,
        state: str,
        *,
        broker_order_id: str | None = None,
        filled_qty: float | None = None,
        raw: Dict[str, Any] | None = None,
        extras: Dict[str, Any] | None = None,
    ) -> None:
        self.store.update_order_state(
            client_order_id,
            state=state,
            broker_order_id=broker_order_id,
            filled_qty=filled_qty,
            raw=raw,
            extra=extras,
        )
        details = {"state": state}
        if extras:
            details.update(extras)
        if broker_order_id:
            details["broker_order_id"] = broker_order_id
        if filled_qty is not None:
            details["filled_qty"] = filled_qty
        self.store.append_journal(
            category="order_state",
            message=state,
            details={"client_order_id": client_order_id, **details},
        )
        self._record_event(
            "order_state",
            client_order_id=client_order_id,
            details=details,
        )
        self._metrics_state(state)
        if state == "filled":
            self._metrics_inc("oms_fills_total")
        elif state == "rejected":
            self._metrics_inc("oms_rejects_total")
        elif state == "canceled":
            self._metrics_inc("oms_cancels_total")

    @staticmethod
    def _is_transient_error(message: str) -> bool:
        if not message:
            return False
        lowered = message.lower()
        return any(
            token in lowered
            for token in (
                "timeout",
                "temporarily",
                "rate limit",
                "too many requests",
                "service unavailable",
                "internal server error",
                "server error",
                "429",
                "503",
            )
        )

    def submit(self, intent: ExecIntent, dry_run: bool = False) -> Dict[str, object]:
        symbol = intent.symbol.upper()
        qty = int(round(float(intent.qty)))
        intent_hash = _intent_key(intent)
        cid = intent.client_order_id

        defaults = get_order_defaults()
        limit_price = float(intent.limit_price)
        tp_price: float | None = None
        sl_price: float | None = None
        if intent.bracket and defaults.allow_brackets:
            tp_pct = _to_float(getattr(defaults, "default_tp_pct", None))
            sl_pct = _to_float(getattr(defaults, "default_sl_pct", None))
            side_multiplier = 1 if intent.side.lower() == "buy" else -1
            if tp_pct:
                tp_price = round(limit_price * (1 + side_multiplier * tp_pct), 2)
            if sl_pct:
                sl_price = round(limit_price * (1 - side_multiplier * sl_pct), 2)

        if not cid and not dry_run:
            prior = self.store.get_order_by_intent(intent_hash)
            if prior and prior.get("client_order_id"):
                cid = str(prior["client_order_id"])

        if not cid and self.state.seen(intent_hash):
            cid = self.state.client_id_for(intent_hash)

        if not cid:
            cid = _unique_cid()

        if qty <= 0:
            log.warning(
                "router.invalid_qty", extra={"symbol": symbol, "qty": intent.qty}
            )
            if not dry_run:
                self.store.upsert_order(
                    client_order_id=cid,
                    state="rejected",
                    intent_hash=intent_hash,
                    symbol=symbol,
                    side=intent.side,
                    qty=qty,
                    limit_price=limit_price,
                    take_profit=tp_price,
                    stop_price=sl_price,
                    tif=defaults.tif,
                    raw={"intent": asdict(intent), "policy": policy_context},
                )
                self._record_transition(
                    cid,
                    "rejected",
                    extras={"reason": "invalid_qty", "symbol": symbol},
                )
            metrics.inc_order_reject("invalid_qty")
            return {"accepted": False, "reason": "invalid_qty", "client_order_id": cid}

        requested_qty = qty
        policy_context: Dict[str, Any] = {}
        if intent.meta:
            policy_context.update(intent.meta)
        policy_context.setdefault("symbol", symbol)
        policy_context.setdefault("side", intent.side.lower())
        policy_context.setdefault("qty", requested_qty)
        policy_context.setdefault("price", limit_price)
        policy_context.setdefault("limit_price", limit_price)
        if policy_context.get("stop_price") is None and sl_price is not None:
            policy_context["stop_price"] = sl_price
        if (
            policy_context.get("atr") is None
            and policy_context.get("stop_price") is not None
        ):
            try:
                stop_val = float(policy_context["stop_price"])
            except (TypeError, ValueError):
                stop_val = None
            if stop_val is not None:
                policy_context.setdefault("atr", abs(limit_price - stop_val))

        allow_trade, gate_info = should_trade(policy_context)
        policy_context.update(gate_info)
        policy_context.setdefault("requested_qty", requested_qty)
        if not allow_trade:
            self._record_event(
                "policy_blocked",
                client_order_id=cid,
                details={
                    "symbol": symbol,
                    "side": intent.side,
                    "reason_codes": gate_info.get("reason_codes"),
                    "policy": policy_context,
                },
            )
            metrics.inc_order_reject("policy_gate_blocked")
            return {
                "accepted": False,
                "reason": "policy_gate_blocked",
                "client_order_id": cid,
                "policy": policy_context,
                "status_code": 202,
            }

        sizing_info = size_position(policy_context)
        policy_context["sizing"] = sizing_info
        sized_qty = int(sizing_info.get("qty") or 0)
        if sized_qty <= 0:
            reason = sizing_info.get("reason", "policy_sizing_zero")
            self._record_event(
                "policy_blocked",
                client_order_id=cid,
                details={
                    "symbol": symbol,
                    "side": intent.side,
                    "reason_codes": [reason],
                    "policy": policy_context,
                },
            )
            metrics.inc_order_reject(reason or "policy_sizing_zero")
            return {
                "accepted": False,
                "reason": reason,
                "client_order_id": cid,
                "policy": policy_context,
                "status_code": 202,
            }

        if sized_qty != requested_qty:
            qty = sized_qty
            intent.qty = float(sized_qty)
        policy_context["approved_qty"] = qty

        self._record_event(
            "policy_allow",
            client_order_id=cid,
            details={
                "symbol": symbol,
                "side": intent.side,
                "qty": qty,
                "policy": policy_context,
            },
        )

        proposal = Proposal(
            symbol=symbol,
            side=intent.side.lower(),
            qty=float(qty),
            price=float(intent.limit_price),
            is_option=intent.asset_class.lower() == "option",
        )

        decision = self.risk.pre_trade_check(proposal)
        if not getattr(decision, "allow", False):
            reason = getattr(decision, "reason", "risk_reject")
            log.info(
                "router.risk_reject",
                extra={"symbol": symbol, "side": intent.side, "reason": reason},
            )
            if not dry_run:
                self.store.upsert_order(
                    client_order_id=cid,
                    state="rejected",
                    intent_hash=intent_hash,
                    symbol=symbol,
                    side=intent.side,
                    qty=qty,
                    limit_price=limit_price,
                    take_profit=tp_price,
                    stop_price=sl_price,
                    tif=defaults.tif,
                    raw={"intent": asdict(intent)},
                )
                extras: Dict[str, Any] = {"reason": reason, "symbol": symbol}
                if getattr(decision, "max_qty", None) is not None:
                    extras["max_qty"] = decision.max_qty
                self._record_transition(cid, "rejected", extras=extras)
            payload: Dict[str, Any] = {
                "accepted": False,
                "reason": reason,
                "client_order_id": cid,
                "policy": policy_context,
            }
            if getattr(decision, "max_qty", None) is not None:
                payload["max_qty"] = decision.max_qty
            metrics.inc_order_reject(reason or "risk_reject")
            return payload

        if dry_run:
            preview = {
                "symbol": symbol,
                "side": intent.side,
                "qty": qty,
                "limit_price": limit_price,
                "take_profit": tp_price,
                "stop_loss": sl_price,
            }
            log.info(
                "router.submit.dry_run",
                extra={"client_order_id": cid, "symbol": symbol},
            )
            return {
                "accepted": False,
                "dry_run": True,
                "client_order_id": cid,
                "order": preview,
                "policy": policy_context,
            }

        existing = self.store.get_order_by_coid(cid)
        if existing:
            log.warning(
                "router.duplicate_client_order_id",
                extra={"symbol": symbol, "client_order_id": cid},
            )
            self._record_event(
                "duplicate_client_order_id",
                client_order_id=cid,
                details={"symbol": symbol},
            )
            self._metrics_inc("oms_rejects_total")
            metrics.inc_order_reject("duplicate_client_order_id")
            return {
                "accepted": False,
                "reason": "duplicate_client_order_id",
                "client_order_id": cid,
            }

        if self.state.seen(intent_hash):
            existing_cid = self.state.client_id_for(intent_hash) or cid
            log.warning(
                "router.duplicate_intent",
                extra={
                    "symbol": symbol,
                    "side": intent.side,
                    "client_order_id": existing_cid,
                },
            )
            self._record_event(
                "duplicate_intent",
                client_order_id=existing_cid,
                details={"symbol": symbol, "side": intent.side},
            )
            self._metrics_inc("oms_rejects_total")
            metrics.inc_order_reject("duplicate_intent")
            return {
                "accepted": False,
                "reason": "duplicate_intent",
                "client_order_id": existing_cid,
            }

        intent_snapshot = {
            "symbol": symbol,
            "side": intent.side,
            "qty": qty,
            "limit_price": limit_price,
            "take_profit": tp_price,
            "stop_loss": sl_price,
            "tif": defaults.tif,
        }
        intent_snapshot["policy"] = policy_context

        self.store.upsert_order(
            client_order_id=cid,
            state="new",
            intent_hash=intent_hash,
            symbol=symbol,
            side=intent.side,
            qty=qty,
            limit_price=limit_price,
            take_profit=tp_price,
            stop_price=sl_price,
            tif=defaults.tif,
            raw={"intent": intent_snapshot, "policy": policy_context},
        )
        self._record_transition(
            cid,
            "new",
            extras={
                "symbol": symbol,
                "side": intent.side,
                "qty": qty,
                "limit_price": limit_price,
            },
        )
        self._record_transition(
            cid,
            "submitting",
            extras={"symbol": symbol, "side": intent.side, "qty": qty},
        )
        self._metrics_inc("oms_submissions_total")

        self.state.remember(intent_hash, cid, symbol=symbol, side=intent.side)

        max_attempts = 3
        backoff = 1.5
        attempt = 0
        order: Dict[str, Any] | None = None
        while attempt < max_attempts:
            try:
                order = self.broker.place_limit_bracket(
                    symbol=symbol,
                    side=intent.side,
                    qty=qty,
                    limit_price=limit_price,
                    take_profit=tp_price,
                    stop_loss=sl_price,
                    client_order_id=cid,
                )
                break
            except AlpacaUnauthorized:
                self.state.forget(intent_hash)
                self._record_transition(
                    cid,
                    "rejected",
                    extras={"reason": "alpaca_unauthorized", "symbol": symbol},
                )
                metrics.inc_order_reject("broker_error_alpaca_unauthorized")
                return {
                    "accepted": False,
                    "reason": "broker_error:alpaca_unauthorized",
                    "client_order_id": cid,
                }
            except AlpacaOrderError as exc:
                message = str(exc)
                if message == "duplicate_client_order_id":
                    self.state.forget(intent_hash)
                    self._record_transition(
                        cid,
                        "rejected",
                        extras={
                            "reason": "duplicate_client_order_id",
                            "symbol": symbol,
                        },
                    )
                    metrics.inc_order_reject("duplicate_client_order_id")
                    return {
                        "accepted": False,
                        "reason": "duplicate_client_order_id",
                        "client_order_id": cid,
                    }
                if self._is_transient_error(message) and attempt < max_attempts - 1:
                    sleep_for = backoff + random.uniform(0, backoff / 2)
                    time.sleep(sleep_for)
                    backoff = min(backoff * 2, 8.0)
                    attempt += 1
                    continue
                self.state.forget(intent_hash)
                self._record_transition(
                    cid,
                    "error",
                    extras={"reason": message, "symbol": symbol},
                )
                metrics.inc_order_reject(f"broker_error_{message or 'unknown'}")
                return {
                    "accepted": False,
                    "reason": f"broker_error:{message}",
                    "client_order_id": cid,
                }
            except Exception as exc:  # noqa: BLE001 - defensive catch
                self.state.forget(intent_hash)
                message = str(exc)
                log.exception(
                    "router.submit.error",
                    extra={"client_order_id": cid, "symbol": symbol, "error": message},
                )
                self._record_transition(
                    cid,
                    "error",
                    extras={"reason": message, "symbol": symbol},
                )
                metrics.inc_order_reject(f"broker_error_{message or 'unknown'}")
                return {
                    "accepted": False,
                    "reason": f"broker_error:{message}",
                    "client_order_id": cid,
                }

        if order is None:
            self.state.forget(intent_hash)
            self._record_transition(
                cid,
                "error",
                extras={"reason": "unknown_error", "symbol": symbol},
            )
            metrics.inc_order_reject("broker_error_unknown")
            return {
                "accepted": False,
                "reason": "broker_error:unknown",
                "client_order_id": cid,
            }

        broker_order_id = order.get("id")
        state = self.broker.map_order_state(order.get("status"))
        filled_qty = _to_float(order.get("filled_qty"))
        avg_fill_price = _to_float(order.get("avg_fill_price"))
        extras = {
            "symbol": symbol,
            "side": intent.side,
            "qty": qty,
            "limit_price": limit_price,
            "status": state,
        }
        self._record_transition(
            cid,
            state,
            broker_order_id=str(broker_order_id) if broker_order_id else None,
            filled_qty=filled_qty,
            raw=order,
            extras=extras,
        )

        if state in {"filled", "partially_filled"} and filled_qty:
            event_ts = order.get("filled_at") or order.get("submitted_at")
            if event_ts and hasattr(event_ts, "isoformat"):
                event_ts = event_ts.isoformat()
            elif event_ts is not None:
                event_ts = str(event_ts)
            self.store.append_execution(
                cid,
                event_type="fill" if state == "filled" else "partial_fill",
                fill_qty=filled_qty,
                fill_price=avg_fill_price,
                event_ts=event_ts,
                raw=order,
            )

        if state in TERMINAL_STATES:
            self.state.forget(intent_hash)
        else:
            self.state.map_provider_id(cid, broker_order_id)

        log.info(
            "router.submit.accepted",
            extra={
                "client_order_id": cid,
                "provider_order_id": broker_order_id,
                "symbol": symbol,
            },
        )
        return {
            "accepted": state not in {"rejected", "error"},
            "client_order_id": cid,
            "provider_order_id": broker_order_id,
            "state": state,
            "policy": policy_context,
        }

    # ------------------------------------------------------------------
    def submit_spread(
        self,
        legs: Sequence[ExecIntent],
        *,
        spread: Mapping[str, Any] | None = None,
        client_order_id: str | None = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Submit a multi-leg spread as coordinated single-leg orders."""

        if not legs:
            raise ValueError("legs_required")

        base_id = client_order_id or _unique_cid()
        spread_meta = dict(spread or {})
        leg_results: list[Dict[str, Any]] = []
        accepted = True
        submitted_leg_ids: list[tuple[str, str | None]] = []

        self._record_event(
            "spread_submit",
            client_order_id=base_id,
            details={
                "legs": len(legs),
                "spread": spread_meta,
            },
        )

        for idx, leg in enumerate(legs, start=1):
            leg_cid = f"{base_id}-L{idx}"
            cloned = replace(leg)
            cloned.client_order_id = leg_cid
            leg_meta = dict(getattr(cloned, "meta", {}) or {})
            leg_meta.setdefault("spread_id", base_id)
            leg_meta.setdefault("spread_leg", idx)
            leg_meta.setdefault("spread_legs", len(legs))
            if spread_meta:
                leg_meta.setdefault("spread", spread_meta)
            cloned.meta = leg_meta  # type: ignore[assignment]

            result = self.submit(cloned, dry_run=dry_run)
            leg_results.append(result)

            if dry_run:
                continue

            submitted_leg_ids.append(
                (
                    result.get("client_order_id", leg_cid),
                    result.get("provider_order_id"),
                )
            )

            if not result.get("accepted", False):
                accepted = False
                failure_reason = result.get("reason", "leg_rejected")
                # Best-effort cancel already accepted legs to keep the spread coherent.
                for prev_cid, provider_id in submitted_leg_ids[:-1]:
                    if provider_id:
                        try:
                            self.broker.cancel_order(provider_id)
                        except Exception:  # pragma: no cover - defensive
                            continue
                    else:
                        try:
                            self.store.update_order_state(prev_cid, state="canceled")
                        except Exception:  # pragma: no cover - defensive
                            continue
                self._record_event(
                    "spread_rejected",
                    client_order_id=base_id,
                    details={"reason": failure_reason, "failed_leg": idx},
                )
                break

        if dry_run:
            return {
                "accepted": False,
                "dry_run": True,
                "client_order_id": base_id,
                "legs": leg_results,
                "spread": spread_meta,
            }

        if accepted:
            self._record_event(
                "spread_submitted",
                client_order_id=base_id,
                details={
                    "child_orders": [res.get("client_order_id") for res in leg_results],
                    "spread": spread_meta,
                },
            )
            return {
                "accepted": True,
                "client_order_id": base_id,
                "legs": leg_results,
                "spread": spread_meta,
            }

        return {
            "accepted": False,
            "client_order_id": base_id,
            "legs": leg_results,
            "spread": spread_meta,
            "reason": leg_results[-1].get("reason"),
        }


class AlpacaRouter:
    """Thin wrapper around :class:`AlpacaAdapter` for dependency injection tests."""

    def __init__(self, adapter: AlpacaAdapter) -> None:
        self.adapter = adapter

    def place_order(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        return self.adapter.place_order(payload)


class MockRouter:
    """Mock router used only when explicitly requested."""

    def __init__(self) -> None:
        self.orders: list[Mapping[str, Any]] = []

    def place_order(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        self.orders.append(dict(payload))
        return payload


def build_router(settings, *, adapter_factory=AlpacaAdapter):
    """Build an order router according to runtime settings."""

    broker = settings.runtime.broker
    profile = settings.runtime.profile
    if profile in {"paper", "live"}:
        if not settings.alpaca.key_id or not settings.alpaca.secret_key:
            raise RuntimeError("Alpaca credentials required for paper/live profile")
        adapter = adapter_factory(
            base_url=settings.alpaca.base_url,
            key_id=settings.alpaca.key_id,
            secret_key=settings.alpaca.secret_key,
        )
        return AlpacaRouter(adapter)
    if broker == "alpaca":
        if not settings.alpaca.key_id or not settings.alpaca.secret_key:
            raise RuntimeError("Alpaca credentials required for alpaca broker")
        adapter = adapter_factory(
            base_url=settings.alpaca.base_url,
            key_id=settings.alpaca.key_id,
            secret_key=settings.alpaca.secret_key,
        )
        return AlpacaRouter(adapter)
    if broker == "mock":
        return MockRouter()
    raise RuntimeError("Invalid broker configuration")
