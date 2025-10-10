"""Alpaca trading adapter."""
from __future__ import annotations

import logging
from typing import Dict

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import OrderRequest

from core.interfaces import Broker
from core.utils import idempotency_key
from app.execution.alpaca_orders import submit_order_async

logger = logging.getLogger(__name__)


class AlpacaBroker(Broker):
    """Thin wrapper around alpaca-py trading client.

    TODO: Implement order types, options order entry, and error handling.
    """

    def __init__(self, client: TradingClient) -> None:
        self._client = client

    async def submit(self, order: Dict) -> Dict:
        request = OrderRequest(**order)
        idem = idempotency_key(order)
        if getattr(request, "client_order_id", None) is None:
            request.client_order_id = idem
        response = await submit_order_async(self._client, request)
        return response.dict()

    async def cancel(self, order_id: str) -> None:
        await self._client.cancel_order_by_id_async(order_id)

    async def replace(self, order_id: str, order: Dict) -> Dict:
        response = await self._client.replace_order_by_id_async(order_id, OrderRequest(**order))
        return response.dict()

    async def positions(self) -> list[Dict]:
        response = await self._client.get_all_positions_async()
        return [pos.dict() for pos in response]

    async def account(self) -> Dict:
        account = await self._client.get_account_async()
        return account.dict()

    async def clock(self) -> Dict:
        clock = await self._client.get_clock_async()
        return clock.dict()

    async def flatten_all(self) -> None:
        await self._client.close_all_positions_async(cancel_orders=True)
