from __future__ import annotations

import datetime as _dt
import logging
import os
import secrets
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Set

from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
from alpaca.trading.requests import LimitOrderRequest, StopLossRequest, TakeProfitRequest

__all__ = [
    "AlpacaAdapter",
    "AlpacaUnauthorized",
    "AlpacaOrderError",
]


log = logging.getLogger(__name__)


class AlpacaUnauthorized(Exception):
    """Raised when Alpaca credentials are invalid or missing."""


class AlpacaOrderError(Exception):
    """Raised when the Alpaca API rejects an order submission."""


def _maybe_float(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return value
    if isinstance(value, (int, float)):
        return float(value)
    return value


def _submitted_at(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:  # pragma: no cover - defensive
            return str(value)
    return str(value)


def _extract_error_code(exc: APIError) -> tuple[Optional[int], str]:
    code: Optional[int] = getattr(exc, "code", None)
    message = getattr(exc, "message", "") or ""
    if not code:
        err = getattr(exc, "error", None)
        if isinstance(err, dict):
            code = err.get("code") or code
            message = err.get("message") or message
    if not message:
        message = str(exc)
    return code, message


def _is_unauthorized(exc: APIError) -> bool:
    status = getattr(exc, "status_code", None)
    if status in {401, 403}:
        return True
    _, message = _extract_error_code(exc)
    return "unauthorized" in message.lower()


class AlpacaAdapter:
    """Thin wrapper over ``TradingClient`` with defensive error handling."""

    def __init__(self) -> None:
        self.client: Optional[TradingClient] = None
        self._configured = False
        self._last_error: Optional[str] = None
        self._seen_client_ids: Set[str] = set()
        key = os.getenv("ALPACA_API_KEY_ID") or os.getenv("APCA_API_KEY_ID")
        secret = os.getenv("ALPACA_API_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")
        base_env = (
            os.getenv("APCA_API_BASE_URL")
            or os.getenv("ALPACA_API_BASE_URL")
            or "https://paper-api.alpaca.markets"
        )
        paper_flag = "paper" in base_env.lower()

        self.key_tail = key[-4:] if key else None
        self._debug: Dict[str, Any] = {
            "base_url": base_env,
            "paper": paper_flag,
            "key_tail": self.key_tail,
        }

        if not key or not secret:
            self._last_error = "missing_credentials"
            return

        os.environ["APCA_API_BASE_URL"] = base_env

        try:
            self.client = TradingClient(api_key=key, secret_key=secret, paper=paper_flag)
            # Cheap auth probe to validate credentials early
            self.client.get_account()
            self._configured = True
            self._last_error = None
        except APIError as exc:  # pragma: no cover - requires live credentials
            if _is_unauthorized(exc):
                self._last_error = "unauthorized"
            else:
                self._last_error = str(exc)
            log.warning(
                "alpaca init failed",
                extra={"comp": "alpaca_adapter", "op": "init", "err": str(exc)},
            )
            self.client = None
            self._configured = False
        except Exception as exc:  # pragma: no cover - SDK constructor guard
            self._last_error = str(exc)
            log.error(
                "alpaca init failed",
                extra={"comp": "alpaca_adapter", "op": "init", "err": str(exc)},
            )
            self.client = None
            self._configured = False

    # ------------------------------------------------------------------
    # public helpers
    def is_configured(self) -> bool:
        return bool(self._configured and self.client is not None)

    def debug_info(self) -> Dict[str, Any]:
        payload = dict(self._debug)
        payload["configured"] = self.is_configured()
        payload["last_error"] = self._last_error
        return payload

    # ------------------------------------------------------------------
    def _gen_client_id(self) -> str:
        today = _dt.datetime.utcnow().strftime("%Y%m%d")
        while True:
            suffix = secrets.token_hex(4)
            cid = f"gt-{today}-{suffix}"
            if cid not in self._seen_client_ids:
                self._seen_client_ids.add(cid)
                return cid

    def _ensure_client(self) -> TradingClient:
        if not self.is_configured():
            self._last_error = "not configured"
            raise AlpacaUnauthorized("not configured")
        assert self.client is not None  # for type checkers
        return self.client

    # ------------------------------------------------------------------
    def place_limit_bracket(
        self,
        symbol: str,
        side: str,
        qty: int,
        limit_price: float,
        take_profit: Optional[float] = None,
        stop_loss: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        client = self._ensure_client()
        side_enum = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
        tif = TimeInForce.DAY

        if client_order_id:
            if client_order_id in self._seen_client_ids:
                client_order_id = self._gen_client_id()
            else:
                self._seen_client_ids.add(client_order_id)
        else:
            client_order_id = self._gen_client_id()

        take_profit_req = None
        stop_loss_req = None
        if take_profit is not None:
            take_profit_req = TakeProfitRequest(limit_price=str(take_profit))
        if stop_loss is not None:
            stop_loss_req = StopLossRequest(stop_price=str(stop_loss))

        request = LimitOrderRequest(
            symbol=symbol,
            qty=str(int(qty)),
            side=side_enum,
            time_in_force=tif,
            limit_price=str(limit_price),
            order_class=OrderClass.BRACKET
            if (take_profit_req or stop_loss_req)
            else OrderClass.SIMPLE,
            client_order_id=client_order_id,
            take_profit=take_profit_req,
            stop_loss=stop_loss_req,
        )

        log.info(
            "alpaca submit",
            extra={
                "comp": "alpaca_adapter",
                "op": "submit",
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "limit": limit_price,
            },
        )

        try:
            order = client.submit_order(order_data=request)
        except APIError as exc:
            if _is_unauthorized(exc):
                self._last_error = "unauthorized"
                log.warning(
                    "alpaca unauthorized",
                    extra={"comp": "alpaca_adapter", "op": "submit", "err": "unauthorized"},
                )
                raise AlpacaUnauthorized("unauthorized") from exc

            code, message = _extract_error_code(exc)
            if code == 40010001 or "client_order_id must be unique" in message.lower():
                log.warning(
                    "alpaca duplicate client id",
                    extra={"comp": "alpaca_adapter", "op": "submit", "err": message},
                )
                # regenerate once
                new_cid = self._gen_client_id()
                request.client_order_id = new_cid
                client_order_id = new_cid
                try:
                    order = client.submit_order(order_data=request)
                except APIError as retry_exc:
                    if _is_unauthorized(retry_exc):
                        self._last_error = "unauthorized"
                        raise AlpacaUnauthorized("unauthorized") from retry_exc
                    self._last_error = str(message)
                    log.error(
                        "alpaca submit failed",
                        extra={
                            "comp": "alpaca_adapter",
                            "op": "submit",
                            "err": str(retry_exc),
                        },
                    )
                    raise AlpacaOrderError(str(retry_exc)) from retry_exc
            else:
                self._last_error = message
                log.error(
                    "alpaca submit failed",
                    extra={"comp": "alpaca_adapter", "op": "submit", "err": message},
                )
                raise AlpacaOrderError(message) from exc
        except Exception as exc:  # pragma: no cover - defensive
            self._last_error = str(exc)
            log.error(
                "alpaca submit error",
                extra={"comp": "alpaca_adapter", "op": "submit", "err": str(exc)},
            )
            raise AlpacaOrderError(str(exc)) from exc

        self._last_error = None
        return self._normalize_order(order)

    # ------------------------------------------------------------------
    def cancel_all(self) -> Dict[str, int]:
        client = self._ensure_client()
        canceled = 0
        failed = 0

        try:
            if hasattr(client, "cancel_orders"):
                result = client.cancel_orders()
                if isinstance(result, Iterable):
                    canceled = len(list(result))
                else:
                    canceled = 0 if result is None else 1
                log.info(
                    "alpaca cancel_all bulk",
                    extra={"comp": "alpaca_adapter", "op": "cancel", "count": canceled},
                )
                self._last_error = None
                return {"canceled": int(canceled), "failed": int(failed)}
        except APIError as exc:
            if _is_unauthorized(exc):
                self._last_error = "unauthorized"
                log.warning(
                    "alpaca cancel unauthorized",
                    extra={"comp": "alpaca_adapter", "op": "cancel", "err": "unauthorized"},
                )
                raise AlpacaUnauthorized("unauthorized") from exc
            self._last_error = str(exc)
            log.error(
                "alpaca cancel error",
                extra={"comp": "alpaca_adapter", "op": "cancel", "err": str(exc)},
            )
            raise AlpacaOrderError(str(exc)) from exc

        try:
            orders = client.get_orders()
            open_statuses = {"new", "accepted", "pending_new", "partially_filled", "open"}
            for order in orders or []:
                status = str(getattr(order, "status", "") or "").lower()
                if status not in open_statuses:
                    continue
                order_id = getattr(order, "id", None)
                try:
                    if order_id is not None:
                        client.cancel_order_by_id(str(order_id))
                    else:  # pragma: no cover - fallback path
                        client.cancel_order(order)
                    canceled += 1
                except APIError as exc:
                    if _is_unauthorized(exc):
                        self._last_error = "unauthorized"
                        raise AlpacaUnauthorized("unauthorized") from exc
                    failed += 1
                    log.warning(
                        "alpaca cancel failed",
                        extra={
                            "comp": "alpaca_adapter",
                            "op": "cancel",
                            "err": str(exc),
                            "order_id": order_id,
                        },
                    )
        except APIError as exc:
            if _is_unauthorized(exc):
                self._last_error = "unauthorized"
                raise AlpacaUnauthorized("unauthorized") from exc
            self._last_error = str(exc)
            log.error(
                "alpaca cancel fetch failed",
                extra={"comp": "alpaca_adapter", "op": "cancel", "err": str(exc)},
            )
            raise AlpacaOrderError(str(exc)) from exc

        self._last_error = None if failed == 0 else "partial"
        return {"canceled": int(canceled), "failed": int(failed)}

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        client = self._ensure_client()
        try:
            client.cancel_order_by_id(str(order_id))
        except APIError as exc:
            if _is_unauthorized(exc):
                self._last_error = "unauthorized"
                raise AlpacaUnauthorized("unauthorized") from exc
            self._last_error = str(exc)
            log.error(
                "alpaca cancel single failed",
                extra={"comp": "alpaca_adapter", "op": "cancel", "err": str(exc), "order_id": order_id},
            )
            raise AlpacaOrderError(str(exc)) from exc

        self._last_error = None
        return {"id": str(order_id), "canceled": True}

    def close_all_positions(self, cancel_orders: bool = True) -> Any:
        client = self._ensure_client()
        try:
            result = client.close_all_positions(cancel_orders=cancel_orders)
        except APIError as exc:
            if _is_unauthorized(exc):
                self._last_error = "unauthorized"
                raise AlpacaUnauthorized("unauthorized") from exc
            self._last_error = str(exc)
            log.error(
                "alpaca close positions failed",
                extra={"comp": "alpaca_adapter", "op": "cancel", "err": str(exc)},
            )
            raise AlpacaOrderError(str(exc)) from exc
        self._last_error = None
        return result

    # ------------------------------------------------------------------
    def fetch_orders(self) -> List[Dict[str, Any]]:
        client = self._ensure_client()
        try:
            orders = client.get_orders()
        except APIError as exc:
            if _is_unauthorized(exc):
                self._last_error = "unauthorized"
                log.warning(
                    "alpaca fetch orders unauthorized",
                    extra={"comp": "alpaca_adapter", "op": "reconcile", "err": "unauthorized"},
                )
                raise AlpacaUnauthorized("unauthorized") from exc
            self._last_error = str(exc)
            log.error(
                "alpaca fetch orders failed",
                extra={"comp": "alpaca_adapter", "op": "reconcile", "err": str(exc)},
            )
            raise AlpacaOrderError(str(exc)) from exc

        normalized = [self._normalize_order(order) for order in orders or []]
        self._last_error = None
        return normalized

    def fetch_positions(self) -> List[Dict[str, Any]]:
        client = self._ensure_client()
        try:
            positions = client.get_all_positions()
        except APIError as exc:
            if _is_unauthorized(exc):
                self._last_error = "unauthorized"
                log.warning(
                    "alpaca fetch positions unauthorized",
                    extra={"comp": "alpaca_adapter", "op": "reconcile", "err": "unauthorized"},
                )
                raise AlpacaUnauthorized("unauthorized") from exc
            self._last_error = str(exc)
            log.error(
                "alpaca fetch positions failed",
                extra={"comp": "alpaca_adapter", "op": "reconcile", "err": str(exc)},
            )
            raise AlpacaOrderError(str(exc)) from exc

        normalized = [self._normalize_position(pos) for pos in positions or []]
        self._last_error = None
        return normalized

    def fetch_account(self) -> Dict[str, Any]:
        client = self._ensure_client()
        try:
            account = client.get_account()
        except APIError as exc:
            if _is_unauthorized(exc):
                self._last_error = "unauthorized"
                log.warning(
                    "alpaca fetch account unauthorized",
                    extra={"comp": "alpaca_adapter", "op": "reconcile", "err": "unauthorized"},
                )
                raise AlpacaUnauthorized("unauthorized") from exc
            self._last_error = str(exc)
            log.error(
                "alpaca fetch account failed",
                extra={"comp": "alpaca_adapter", "op": "reconcile", "err": str(exc)},
            )
            raise AlpacaOrderError(str(exc)) from exc

        payload = {
            "id": getattr(account, "id", None),
            "status": getattr(account, "status", None),
            "equity": _maybe_float(getattr(account, "equity", None)),
            "cash": _maybe_float(getattr(account, "cash", None)),
            "buying_power": _maybe_float(getattr(account, "buying_power", None)),
            "portfolio_value": _maybe_float(getattr(account, "portfolio_value", None)),
            "day_pnl": _maybe_float(
                getattr(account, "day_pl", None) or getattr(account, "day_profit_loss", None)
            ),
            "pattern_day_trader": bool(getattr(account, "pattern_day_trader", False)),
            "daytrade_count": int(getattr(account, "daytrade_count", 0) or 0),
        }
        self._last_error = None
        return payload

    # ------------------------------------------------------------------
    def _normalize_order(self, order: Any) -> Dict[str, Any]:
        if isinstance(order, dict):
            payload = dict(order)
        else:
            payload = {
                "id": getattr(order, "id", None),
                "symbol": getattr(order, "symbol", None),
                "side": getattr(order, "side", None),
                "qty": getattr(order, "qty", None),
                "limit_price": getattr(order, "limit_price", None),
                "status": getattr(order, "status", None),
                "submitted_at": getattr(order, "submitted_at", None),
                "client_order_id": getattr(order, "client_order_id", None),
                "avg_fill_price": getattr(order, "avg_fill_price", None),
            }
        payload["qty"] = _maybe_float(payload.get("qty"))
        payload["limit_price"] = _maybe_float(payload.get("limit_price"))
        payload["avg_fill_price"] = _maybe_float(payload.get("avg_fill_price"))
        payload["submitted_at"] = _submitted_at(payload.get("submitted_at"))
        return payload

    def _normalize_position(self, position: Any) -> Dict[str, Any]:
        if isinstance(position, dict):
            payload = dict(position)
        else:
            payload = {
                "symbol": getattr(position, "symbol", None),
                "qty": getattr(position, "qty", None),
                "avg_entry_price": getattr(position, "avg_entry_price", None),
                "market_value": getattr(position, "market_value", None),
                "unrealized_pl": getattr(position, "unrealized_pl", None),
                "side": getattr(position, "side", None),
            }
        for key in ("qty", "avg_entry_price", "market_value", "unrealized_pl"):
            payload[key] = _maybe_float(payload.get(key))
        return payload
