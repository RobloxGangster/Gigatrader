from __future__ import annotations

import asyncio
from functools import partial
from typing import Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    LimitOrderRequest,
    MarketOrderRequest,
    StopLossRequest,
    TakeProfitRequest,
)
from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce


def submit_order_sync(client: TradingClient, order_req):
    return client.submit_order(order_data=order_req)


async def submit_order_async(client: TradingClient, order_req):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(submit_order_sync, client, order_req))


def build_market_order(
    symbol: str,
    qty: int,
    side: str,
    tif: str = "DAY",
    client_order_id: Optional[str] = None,
):
    return MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide(side.upper()),
        time_in_force=TimeInForce(tif.upper()),
        client_order_id=client_order_id,
    )


def build_limit_order(
    symbol: str,
    qty: int,
    side: str,
    limit_price: float,
    tif: str = "DAY",
    client_order_id: Optional[str] = None,
):
    if limit_price is None:
        raise ValueError("limit orders require a limit_price")
    return LimitOrderRequest(
        symbol=symbol,
        qty=qty,
        limit_price=float(limit_price),
        side=OrderSide(side.upper()),
        time_in_force=TimeInForce(tif.upper()),
        client_order_id=client_order_id,
    )


def build_bracket_market_order(
    symbol: str,
    qty: int,
    side: str,
    take_profit_limit: float,
    stop_loss: float,
    tif: str = "GTC",
    client_order_id: Optional[str] = None,
):
    return MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide(side.upper()),
        time_in_force=TimeInForce(tif.upper()),
        order_class=OrderClass.BRACKET,
        take_profit=TakeProfitRequest(limit_price=float(take_profit_limit)),
        stop_loss=StopLossRequest(stop_price=float(stop_loss)),
        client_order_id=client_order_id,
    )


def build_bracket_limit_order(
    symbol: str,
    qty: int,
    side: str,
    limit_price: float,
    take_profit_limit: float,
    stop_loss: float,
    tif: str = "GTC",
    client_order_id: Optional[str] = None,
):
    if limit_price is None:
        raise ValueError("bracket limit orders require limit_price")
    return LimitOrderRequest(
        symbol=symbol,
        qty=qty,
        limit_price=float(limit_price),
        side=OrderSide(side.upper()),
        time_in_force=TimeInForce(tif.upper()),
        order_class=OrderClass.BRACKET,
        take_profit=TakeProfitRequest(limit_price=float(take_profit_limit)),
        stop_loss=StopLossRequest(stop_price=float(stop_loss)),
        client_order_id=client_order_id,
    )
