"""Order routing with risk controls and Alpaca submission."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any, Dict
from app.risk import Proposal, RiskManager
from app.state import ExecutionState
from core.config import get_order_defaults

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


class OrderRouter:
    """Coordinates risk checks, idempotency and Alpaca order submission."""

    def __init__(self, risk: RiskManager, state: ExecutionState) -> None:
        self.risk = risk
        self.state = state

        from app.execution.alpaca_adapter import AlpacaAdapter

        self.broker = AlpacaAdapter()

    def submit(self, intent: ExecIntent) -> Dict[str, object]:
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

        key = _intent_key(intent)
        if self.state.seen(key):
            cid = self.state.client_id_for(key)
            log.warning(
                "router.duplicate_intent",
                extra={"symbol": symbol, "side": intent.side, "client_order_id": cid},
            )
            return {"accepted": False, "reason": "duplicate_intent", "client_order_id": cid}

        cid = intent.client_order_id or _unique_cid()
        self.state.remember(key, cid, symbol=symbol, side=intent.side)

        defaults = get_order_defaults()
        tp_pct = defaults.default_tp_pct if intent.bracket else None
        sl_pct = defaults.default_sl_pct if intent.bracket else None
        try:
            order = self.broker.place_limit_bracket(
                symbol=symbol,
                side=intent.side,
                qty=qty,
                limit_price=float(intent.limit_price),
                client_order_id=cid,
                tp_pct=tp_pct,
                sl_pct=sl_pct,
                tif=defaults.tif,
            )
            provider_id = getattr(order, "id", None)
            self.state.map_provider_id(cid, provider_id)
            log.info(
                "router.submit.accepted",
                extra={"client_order_id": cid, "provider_order_id": provider_id, "symbol": symbol},
            )
            return {"accepted": True, "client_order_id": cid, "provider_order_id": provider_id}
        except Exception as exc:  # noqa: BLE001 - propagate after logging
            log.exception(
                "router.submit.error",
                extra={"client_order_id": cid, "symbol": symbol, "error": str(exc)},
            )
            return {"accepted": False, "reason": f"broker_error:{exc}", "client_order_id": cid}
