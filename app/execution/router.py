"""Order routing with risk controls and Alpaca submission."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict

from app.risk import Proposal, RiskManager
from app.state import ExecutionState
from core.config import get_order_defaults

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

    def __init__(self, risk: RiskManager, state: ExecutionState) -> None:
        self.risk = risk
        self.state = state
        self.broker = AlpacaAdapter()

    def submit(self, intent: ExecIntent, dry_run: bool = False) -> Dict[str, object]:
        symbol = intent.symbol.upper()
        qty = int(round(float(intent.qty)))
        if qty <= 0:
            log.warning("router.invalid_qty", extra={"symbol": symbol, "qty": intent.qty})
            return {"accepted": False, "reason": "invalid_qty"}

        proposal = Proposal(
            symbol=symbol,
            side=intent.side.lower(),
            qty=float(qty),
            price=float(intent.limit_price),
            is_option=intent.asset_class.lower() == "option",
        )

        decision = self.risk.pre_trade_check(proposal)
        if not getattr(decision, "allow", False):
            log.info(
                "router.risk_reject",
                extra={"symbol": symbol, "side": intent.side, "reason": getattr(decision, "reason", None)},
            )
            payload: Dict[str, Any] = {"accepted": False, "reason": getattr(decision, "reason", "risk_reject")}
            if getattr(decision, "max_qty", None) is not None:
                payload["max_qty"] = decision.max_qty
            return payload

        cid = intent.client_order_id or _unique_cid()
        key = _intent_key(intent)
        if not dry_run and self.state.seen(key):
            existing_cid = self.state.client_id_for(key)
            log.warning(
                "router.duplicate_intent",
                extra={"symbol": symbol, "side": intent.side, "client_order_id": existing_cid},
            )
            return {"accepted": False, "reason": "duplicate_intent", "client_order_id": existing_cid}

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
            return {"accepted": False, "dry_run": True, "client_order_id": cid, "order": preview}

        self.state.remember(key, cid, symbol=symbol, side=intent.side)
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
        except AlpacaUnauthorized:
            self.state.forget(key)
            return {
                "accepted": False,
                "reason": "broker_error:alpaca_unauthorized",
                "client_order_id": cid,
            }
        except AlpacaOrderError as exc:
            self.state.forget(key)
            return {
                "accepted": False,
                "reason": f"broker_error:{exc}",
                "client_order_id": cid,
            }
        except Exception as exc:  # noqa: BLE001 - defensive catch
            self.state.forget(key)
            log.exception(
                "router.submit.error",
                extra={"client_order_id": cid, "symbol": symbol, "error": str(exc)},
            )
            return {"accepted": False, "reason": f"broker_error:{exc}", "client_order_id": cid}

        actual_cid = str(order.get("client_order_id") or cid)
        if actual_cid != cid:
            self.state.update_client_id(cid, actual_cid)
            cid = actual_cid

        provider_id = order.get("id")
        self.state.map_provider_id(cid, provider_id)
        log.info(
            "router.submit.accepted",
            extra={"client_order_id": cid, "provider_order_id": provider_id, "symbol": symbol},
        )
        return {"accepted": True, "client_order_id": cid, "provider_order_id": provider_id}
