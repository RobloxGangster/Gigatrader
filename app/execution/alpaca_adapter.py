from __future__ import annotations

import os
import time
import secrets
from enum import Enum
from decimal import Decimal
from typing import Any, List

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    GetOrdersRequest,
    LimitOrderRequest,
    TakeProfitRequest,
    StopLossRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass, OrderType
from alpaca.common.exceptions import APIError

from core.config import get_alpaca_settings


def _unique_cid(prefix: str | None = None) -> str:
    """Alpaca requires unique client_order_id. Keep short & readable."""
    p = (prefix or os.getenv("ORDER_CLIENT_ID_PREFIX", "gt")).strip()
    ts = time.strftime("%y%m%d%H%M%S", time.gmtime())
    rnd = secrets.token_hex(3)
    return f"{p}-{ts}-{rnd}"[:48]


def _parse_apierror(exc: APIError) -> tuple[int | None, str]:
    code = None
    msg = ""
    try:
        err = getattr(exc, "error", None)
        if isinstance(err, dict):
            code = err.get("code")
            msg = err.get("message") or ""
    except Exception:  # pragma: no cover - defensive best effort
        pass
    if not msg:
        msg = str(exc)
    return code, msg


class AlpacaAdapter:
    def __init__(self) -> None:
        self.settings = get_alpaca_settings()
        self.client: TradingClient | None = None
        self._ensure_paper()
        if self.settings.api_key_id and self.settings.api_secret_key:
            self.client = TradingClient(
                self.settings.api_key_id,
                self.settings.api_secret_key,
                paper=bool(self.settings.paper),
                raw_data=True,
            )

    def _ensure_paper(self) -> None:
        base_url = (self.settings.base_url or "").lower()
        if not bool(self.settings.paper):
            self.client = None
            raise RuntimeError("not_paper_environment")
        if base_url and "api.alpaca.markets" in base_url and "paper" not in base_url:
            self.client = None
            raise RuntimeError("not_paper_environment")

    def configured(self) -> bool:
        return self.client is not None

    def get_account(self) -> dict[str, Any]:
        if not self.configured():
            raise RuntimeError("alpaca_not_configured")
        try:
            return self.client.get_account()  # type: ignore[union-attr]
        except APIError as exc:
            _, msg = _parse_apierror(exc)
            if "unauthorized" in msg.lower():
                raise RuntimeError("alpaca_unauthorized")
            raise

    def get_account_summary(self) -> dict[str, Any]:
        acct = self.get_account()
        return {k: acct.get(k) for k in ("id", "status", "currency", "cash", "portfolio_value")}

    def list_orders(self, status: str = "open", limit: int = 50) -> list[dict[str, Any]]:
        if not self.configured():
            raise RuntimeError("alpaca_not_configured")
        req = GetOrdersRequest(status=status, limit=limit)
        return self.client.get_orders(filter=req)  # type: ignore[union-attr]

    def get_open_orders(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.list_orders(status="open", limit=limit)

    def cancel_all(self) -> Any:
        if not self.configured():
            raise RuntimeError("alpaca_not_configured")
        try:
            return self.client.cancel_orders()  # type: ignore[union-attr]
        except TypeError:
            return self.client.cancel_all_orders()  # type: ignore[union-attr]

    def cancel_all_open_orders(self) -> dict[str, Any]:
        resp = self.cancel_all()
        canceled: List[str]
        if isinstance(resp, (list, tuple, set)):
            canceled = []
            for item in resp:
                if isinstance(item, dict):
                    canceled.append(str(item.get("id")))
                else:
                    canceled.append(str(getattr(item, "id", item)))
        elif isinstance(resp, dict):
            canceled = [str(resp.get("id")) if resp.get("id") is not None else str(resp)]
        else:
            canceled = [str(resp)] if resp is not None else []
        return {"canceled": canceled, "failed": []}

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        if not self.configured():
            raise RuntimeError("alpaca_not_configured")
        self.client.cancel_order_by_id(order_id)  # type: ignore[union-attr]
        return {"ok": True, "id": order_id}

    def get_positions(self) -> list[dict[str, Any]]:
        if not self.configured():
            raise RuntimeError("alpaca_not_configured")
        return self.client.get_all_positions()  # type: ignore[union-attr]

    def close_all_positions(self, cancel_orders: bool = True) -> Any:
        if not self.configured():
            raise RuntimeError("alpaca_not_configured")
        return self.client.close_all_positions(cancel_orders=cancel_orders)  # type: ignore[union-attr]

    def _serialize_request(self, req: LimitOrderRequest) -> dict[str, Any]:
        def _convert(val: Any) -> Any:
            if isinstance(val, Enum):
                return val.value
            if hasattr(val, "model_dump"):
                return self._serialize_request(val)  # type: ignore[arg-type]
            if isinstance(val, dict):
                return {k: _convert(v) for k, v in val.items() if v is not None}
            if isinstance(val, (list, tuple)):
                return [_convert(v) for v in val if v is not None]
            return val

        data = req.model_dump()  # type: ignore[call-arg]
        return {k: _convert(v) for k, v in data.items() if v is not None}

    def place_limit_bracket(
        self,
        symbol: str,
        side: str,
        qty: int,
        limit_price: float | Decimal,
        take_profit_pct: float | None = None,
        stop_loss_pct: float | None = None,
        client_order_id: str | None = None,
        tif: str = "day",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        if not self.configured():
            raise RuntimeError("alpaca_not_configured")

        side_enum = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
        tif_enum = TimeInForce.DAY if tif.lower() == "day" else TimeInForce.GTC
        cid = client_order_id or _unique_cid()
        lp = str(limit_price)

        tp = None
        sl = None
        if take_profit_pct:
            limit_f = float(limit_price)
            px = round(
                limit_f * (1 + (take_profit_pct / 100.0) * (1 if side_enum == OrderSide.BUY else -1)), 2
            )
            tp = TakeProfitRequest(limit_price=str(px))
        if stop_loss_pct:
            limit_f = float(limit_price)
            px = round(
                limit_f * (1 - (stop_loss_pct / 100.0) * (1 if side_enum == OrderSide.BUY else -1)), 2
            )
            sl = StopLossRequest(stop_price=str(px))

        req = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side_enum,
            time_in_force=tif_enum,
            limit_price=lp,
            order_class=OrderClass.BRACKET if (tp or sl) else OrderClass.SIMPLE,
            client_order_id=cid,
            take_profit=tp,
            stop_loss=sl,
            type=OrderType.LIMIT,
        )

        if dry_run:
            return {
                "dry_run": True,
                "request": self._serialize_request(req),
                "client_order_id": cid,
            }

        try:
            order = self.client.submit_order(order_data=req)  # type: ignore[union-attr]
        except APIError as exc:
            code, msg = _parse_apierror(exc)
            low = (msg or "").lower()
            if "unauthorized" in low:
                raise RuntimeError("alpaca_unauthorized")
            if code == 40010001 or "client_order_id must be unique" in low:
                req.client_order_id = _unique_cid()
                order = self.client.submit_order(order_data=req)  # type: ignore[union-attr]
            else:
                raise
        return order
