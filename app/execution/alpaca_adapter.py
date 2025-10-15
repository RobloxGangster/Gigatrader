from __future__ import annotations

import datetime as _dt
import logging
import os
import secrets
import asyncio
import inspect
import random
from contextlib import suppress
from decimal import Decimal
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Set

from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
from alpaca.trading.requests import LimitOrderRequest, StopLossRequest, TakeProfitRequest

from app.oms.store import OmsStore

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
        self._api_key: Optional[str] = None
        self._api_secret: Optional[str] = None
        self._base_url: Optional[str] = None
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

        self._api_key = key
        self._api_secret = secret
        self._base_url = base_env
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

        provided_client_id = client_order_id is not None
        if client_order_id:
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
                if not provided_client_id:
                    new_cid = self._gen_client_id()
                    self._seen_client_ids.add(new_cid)
                    request.client_order_id = new_cid
                    client_order_id = new_cid
                    try:
                        order = client.submit_order(order_data=request)
                    except APIError as retry_exc:
                        if _is_unauthorized(retry_exc):
                            self._last_error = "unauthorized"
                            raise AlpacaUnauthorized("unauthorized") from retry_exc
                        self._last_error = "duplicate_client_order_id"
                        raise AlpacaOrderError("duplicate_client_order_id") from retry_exc
                else:
                    self._last_error = "duplicate_client_order_id"
                    raise AlpacaOrderError("duplicate_client_order_id") from exc
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

    # ------------------------------------------------------------------
    @staticmethod
    def map_order_state(status: str | None) -> str:
        if not status:
            return "new"
        normalized = str(status).lower()
        mapping = {
            "new": "new",
            "pending_new": "new",
            "accepted": "accepted",
            "acknowledged": "accepted",
            "open": "accepted",
            "partially_filled": "partially_filled",
            "partial": "partially_filled",
            "filled": "filled",
            "canceled": "canceled",
            "cancelled": "canceled",
            "expired": "canceled",
            "replaced": "accepted",
            "rejected": "rejected",
            "suspended": "error",
            "stopped": "canceled",
        }
        if normalized in mapping:
            return mapping[normalized]
        if "reject" in normalized:
            return "rejected"
        if "cancel" in normalized or "close" in normalized:
            return "canceled"
        if "fill" in normalized:
            return "filled"
        if "error" in normalized:
            return "error"
        return "new"

    def _normalize_trade_update(self, update: Any) -> Dict[str, Any]:
        payload: Dict[str, Any]
        raw = update
        if hasattr(update, "data"):
            raw = getattr(update, "data")
        if isinstance(raw, dict):
            payload = dict(raw)
        else:
            payload = {}
            for attr in ("event", "timestamp", "order", "execution"):
                if hasattr(raw, attr):
                    payload[attr] = getattr(raw, attr)

        order_info = payload.get("order")
        if order_info is None and hasattr(raw, "order"):
            order_info = getattr(raw, "order")
        normalized_order = self._normalize_order(order_info) if order_info is not None else {}

        event = payload.get("event") or payload.get("type")
        state = self.map_order_state(normalized_order.get("status"))
        execution_info = payload.get("execution")
        if execution_info and not isinstance(execution_info, dict):  # pragma: no cover - depends on SDK
            execution_info = {
                key: getattr(execution_info, key, None)
                for key in ("qty", "price", "timestamp")
            }
        return {
            "event": event,
            "state": state,
            "client_order_id": normalized_order.get("client_order_id"),
            "broker_order_id": normalized_order.get("id"),
            "filled_qty": normalized_order.get("filled_qty") or normalized_order.get("qty"),
            "avg_fill_price": normalized_order.get("avg_fill_price"),
            "order": normalized_order,
            "execution": execution_info,
            "raw": payload,
        }

    async def start_stream(
        self,
        on_update: Callable[[Dict[str, Any]], Awaitable[None] | None],
        stop_event: asyncio.Event,
    ) -> None:
        if not self.is_configured():
            raise AlpacaUnauthorized("not configured")
        try:
            from alpaca.trading.stream import TradingStream
        except Exception as exc:  # pragma: no cover - import guard
            log.warning("alpaca stream unavailable: %s", exc)
            return

        backoff = 1.0
        while not stop_event.is_set():
            try:
                stream = TradingStream(
                    api_key=self._api_key,
                    secret_key=self._api_secret,
                    base_url=self._base_url,
                )

                async def _handler(data: Any) -> None:
                    payload = self._normalize_trade_update(data)
                    result = on_update(payload)
                    if inspect.isawaitable(result):
                        await result

                stream.subscribe_trade_updates(_handler)

                async def _watch_stop() -> None:
                    await stop_event.wait()
                    with suppress(Exception):
                        await stream.close()

                stopper = asyncio.create_task(_watch_stop())
                await stream._run_forever()
                stopper.cancel()
                with suppress(Exception):
                    await stream.close()
                backoff = 1.0
            except AlpacaUnauthorized:
                raise
            except Exception as exc:  # pragma: no cover - network path
                log.warning(
                    "alpaca stream error", extra={"comp": "alpaca_adapter", "err": str(exc)}
                )
                await asyncio.sleep(backoff + random.uniform(0, backoff / 2))
                backoff = min(backoff * 2, 30.0)

    # ------------------------------------------------------------------
    def fetch_and_merge_orders(
        self,
        store: OmsStore,
        *,
        target_client_order_id: str | None = None,
    ) -> Dict[str, Any]:
        orders = self.fetch_orders()
        positions: List[Dict[str, Any]] = []
        try:
            positions = self.fetch_positions()
        except AlpacaUnauthorized:
            raise
        except Exception:  # pragma: no cover - tolerates missing permissions
            pass
        store.replace_positions(positions)
        matched: Optional[Dict[str, Any]] = None
        for order in orders:
            cid = str(order.get("client_order_id") or "")
            state = self.map_order_state(order.get("status"))
            store.upsert_order(
                client_order_id=cid,
                state=state,
                broker_order_id=str(order.get("id") or "") or None,
                symbol=order.get("symbol"),
                side=order.get("side"),
                qty=_maybe_float(order.get("qty")),
                filled_qty=_maybe_float(order.get("filled_qty")),
                limit_price=_maybe_float(order.get("limit_price")),
                stop_price=_maybe_float(order.get("stop_price")),
                take_profit=_maybe_float(order.get("take_profit")),
                tif=order.get("time_in_force") or order.get("tif"),
                raw=order,
            )
            if target_client_order_id and cid == target_client_order_id:
                matched = order
        snapshot = store.metrics_snapshot()
        return {
            "orders": orders,
            "positions": positions,
            "target_order": matched,
            "metrics": snapshot,
        }
