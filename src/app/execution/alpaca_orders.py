from __future__ import annotations
import asyncio
from functools import partial
from typing import Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    TakeProfitRequest,
    StopLossRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
from alpaca.common.exceptions import APIError  # noqa: F401

# --- Core sync call ---
def submit_order_sync(client: TradingClient, order_req):
    """
    Thin wrapper over TradingClient.submit_order(order_data=...).
    Raises underlying APIError on failure.
    """
    return client.submit_order(order_data=order_req)

# --- Async wrapper to fit asyncio-based engines ---
async def submit_order_async(client: TradingClient, order_req):
    """
    Run the sync submit_order in a thread so callers can `await` it safely.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(submit_order_sync, client, order_req))

# --- Convenience builders (ready for callers) ---
def build_market_order(symbol: str, qty: int, side: str, tif: str = "DAY", client_order_id: Optional[str] = None):
    return MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide(side.upper()),
        time_in_force=TimeInForce(tif.upper()),
        client_order_id=client_order_id,
    )

def build_limit_order(symbol: str, qty: int, side: str, limit_price: float, tif: str = "DAY", client_order_id: Optional[str] = None):
    return LimitOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide(side.upper()),
        time_in_force=TimeInForce(tif.upper()),
        limit_price=limit_price,
        client_order_id=client_order_id,
    )

def build_bracket_market_order(
    symbol: str, qty: int, side: str, take_profit_limit: float, stop_loss: float, tif: str = "GTC", client_order_id: Optional[str] = None
):
    return MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide(side.upper()),
        time_in_force=TimeInForce(tif.upper()),
        order_class=OrderClass.BRACKET,
        take_profit=TakeProfitRequest(limit_price=take_profit_limit),
        stop_loss=StopLossRequest(stop_price=stop_loss),
        client_order_id=client_order_id,
    )
