"""Async wrapper around the Alpaca Trading API used by the execution engine."""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional

from app.config import get_settings
from app.rate_limit import RateLimitError, backoff_request
from services.telemetry import record_order_latency_async

# NOTE: import alpaca types lazily so unit tests can stub the adapter without installing deps.


class AlpacaAdapter:
    """Thin async wrapper around alpaca-py Trading API + order updates stream."""

    def __init__(
        self,
        *,
        client: Optional[object] = None,
        settings: Optional[object] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._loop = loop
        self._lock = asyncio.Lock()
        self._max_retries = int(os.getenv("EXEC_MAX_RETRIES", "5"))
        self._max_wait = float(os.getenv("EXEC_RETRY_MAX_WAIT_SEC", "30"))

    async def _ensure_client(self) -> object:
        if self._client is not None:
            return self._client
        async with self._lock:
            if self._client is not None:
                return self._client
            settings = self._settings or get_settings()
            # Deferred imports so tests can stub without importing alpaca.
            from alpaca.trading.client import TradingClient

            self._client = TradingClient(
                settings.alpaca_key_id,
                settings.alpaca_secret_key,
                paper=settings.paper,
            )
            return self._client

    async def _run_blocking(self, fn: Callable[[], Any]) -> Any:
        loop = self._loop or asyncio.get_running_loop()
        return await loop.run_in_executor(None, fn)

    async def _call_with_retries(self, fn: Callable[[], Awaitable[Any]]) -> Any:
        delay = 1.0
        for attempt in range(self._max_retries + 1):
            try:
                return await backoff_request(fn, max_retries=self._max_retries)
            except RateLimitError:
                if attempt == self._max_retries:
                    raise
                await asyncio.sleep(delay)
            except Exception as exc:  # pragma: no cover - network errors only occur live
                status = getattr(exc, "status_code", None)
                if status is None:
                    status = getattr(getattr(exc, "response", None), "status_code", None)
                if status is not None and 500 <= int(status) < 600:
                    if attempt == self._max_retries:
                        raise
                    await asyncio.sleep(delay)
                else:
                    raise
            delay = min(delay * 2, self._max_wait)
        raise RateLimitError("exhausted retries")

    async def submit_order(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Submit order via REST; returns JSON-like dict with id, status, client_order_id."""

        client = await self._ensure_client()
        client_oid = payload.get("client_order_id") or str(uuid.uuid4())

        async def _call() -> Any:
            from alpaca.trading.enums import AssetClass as AlpacaAssetClass
            from alpaca.trading.enums import OrderClass, OrderSide, OrderType, TimeInForce
            from alpaca.trading.requests import (
                LimitOrderRequest,
                MarketOrderRequest,
                StopLossRequest,
                TakeProfitRequest,
            )

            side = OrderSide(payload["side"].upper())
            time_in_force = TimeInForce.DAY
            qty = payload["qty"]
            symbol = payload["symbol"]
            limit_price = payload.get("limit_price")
            asset_class = payload.get("asset_class", "equity")
            alpaca_asset = (
                AlpacaAssetClass.OPTION if asset_class == "option" else AlpacaAssetClass.US_EQUITY
            )

            order_type = OrderType.LIMIT if limit_price is not None else OrderType.MARKET
            req_cls = LimitOrderRequest if order_type == OrderType.LIMIT else MarketOrderRequest
            kwargs: Dict[str, Any] = {
                "symbol": symbol,
                "qty": qty,
                "side": side,
                "time_in_force": time_in_force,
                "client_order_id": client_oid,
                "asset_class": alpaca_asset,
            }
            if limit_price is not None:
                kwargs["limit_price"] = limit_price
            tp = payload.get("take_profit")
            sl = payload.get("stop_loss")
            if tp or sl:
                kwargs["order_class"] = OrderClass.BRACKET
                if tp:
                    kwargs["take_profit"] = TakeProfitRequest(limit_price=tp["limit_price"])
                if sl:
                    kwargs["stop_loss"] = StopLossRequest(stop_price=sl["stop_price"])
            request = req_cls(**kwargs)
            return await self._run_blocking(lambda: client.submit_order(request))

        async with record_order_latency_async():
            resp = await self._call_with_retries(_call)
        return {
            "id": str(getattr(resp, "id", "")),
            "status": str(getattr(resp, "status", "")),
            "client_order_id": client_oid,
        }

    async def cancel_order(self, order_id: str) -> None:
        client = await self._ensure_client()

        async def _call() -> Any:
            return await self._run_blocking(lambda: client.cancel_order_by_id(order_id))

        await self._call_with_retries(_call)

    async def replace_order(self, order_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        client = await self._ensure_client()

        async def _call() -> Any:
            from alpaca.trading.requests import ReplaceOrderRequest

            request = ReplaceOrderRequest(**payload)
            return await self._run_blocking(lambda: client.replace_order_by_id(order_id, request))

        resp = await self._call_with_retries(_call)
        return {
            "id": str(getattr(resp, "id", order_id)),
            "status": str(getattr(resp, "status", "")),
        }
