"""Alpaca trading adapter."""

from __future__ import annotations

import logging
from typing import Any, Dict

from alpaca.trading.client import TradingClient

try:
    from alpaca.trading.requests import OrderRequest
except (ImportError, ModuleNotFoundError):  # pragma: no cover - env guard
    OrderRequest = None  # type: ignore[assignment]

from app.execution.alpaca_orders import submit_order_async
from core.interfaces import Broker
from core.utils import idempotency_key


def _as_dict(payload: Any) -> Dict:
    if hasattr(payload, "model_dump"):
        return payload.model_dump()  # type: ignore[return-value]
    if hasattr(payload, "dict"):
        return payload.dict()  # type: ignore[return-value]
    raise TypeError(f"Unsupported payload type for serialization: {type(payload)!r}")

logger = logging.getLogger(__name__)


class AlpacaBroker(Broker):
    """Thin wrapper around alpaca-py trading client.

    TODO: Implement order types, options order entry, and error handling.
    """

    def __init__(self, client: TradingClient) -> None:
        self._client = client

    async def submit(self, order: Dict) -> Dict:
        if OrderRequest is None:  # pragma: no cover - defensive guard
            raise RuntimeError("alpaca-py OrderRequest class is unavailable")
        request = OrderRequest(**order)
        idem = idempotency_key(order)
        if getattr(request, "client_order_id", None) is None:
            request.client_order_id = idem
        response = await submit_order_async(self._client, request)
        return _as_dict(response)

    async def cancel(self, order_id: str) -> None:
        await self._client.cancel_order_by_id_async(order_id)

    async def replace(self, order_id: str, order: Dict) -> Dict:
        if OrderRequest is None:  # pragma: no cover - defensive guard
            raise RuntimeError("alpaca-py OrderRequest class is unavailable")
        response = await self._client.replace_order_by_id_async(order_id, OrderRequest(**order))
        return _as_dict(response)

    async def positions(self) -> list[Dict]:
        response = await self._client.get_all_positions_async()
        return [_as_dict(pos) for pos in response]

    async def account(self) -> Dict:
        account = await self._client.get_account_async()
        return _as_dict(account)

    async def clock(self) -> Dict:
        clock = await self._client.get_clock_async()
        return _as_dict(clock)

    async def flatten_all(self) -> None:
        await self._client.close_all_positions_async(cancel_orders=True)
