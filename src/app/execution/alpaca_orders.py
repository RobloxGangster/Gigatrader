from __future__ import annotations

import asyncio
from functools import partial
from typing import Any, Optional

try:  # pragma: no cover - allow repo to run without alpaca-py for tests
    from alpaca.trading.client import TradingClient
    from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
    from alpaca.trading.requests import (
        LimitOrderRequest,
        MarketOrderRequest,
        StopLossRequest,
        TakeProfitRequest,
    )
except ModuleNotFoundError:  # pragma: no cover - fallback types for tooling/tests
    TradingClient = Any  # type: ignore

    class OrderSide(str):  # type: ignore
        def __new__(cls, value: str):
            return str.__new__(cls, value)

    class TimeInForce(str):  # type: ignore
        def __new__(cls, value: str):
            return str.__new__(cls, value)

    class OrderClass:  # type: ignore
        BRACKET = "bracket"

    class MarketOrderRequest(dict):  # type: ignore
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.__dict__.update(kwargs)

    class LimitOrderRequest(MarketOrderRequest):  # type: ignore
        pass

    class TakeProfitRequest(dict):  # type: ignore
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.__dict__.update(kwargs)

    class StopLossRequest(TakeProfitRequest):  # type: ignore
        pass


def submit_order_sync(client: TradingClient, order_req: Any) -> Any:
    """Submit an order synchronously through the Alpaca trading client."""

    return client.submit_order(order_data=order_req)


async def submit_order_async(client: TradingClient, order_req: Any) -> Any:
    """Run :func:`submit_order_sync` in a thread for asyncio callers."""

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(submit_order_sync, client, order_req))


def _normalise_side(side: str) -> OrderSide:
    token = side.upper()
    try:
        return OrderSide[token]  # type: ignore[index]
    except (KeyError, TypeError, AttributeError):
        return OrderSide(side.lower())


def _normalise_tif(tif: str) -> TimeInForce:
    token = tif.upper()
    try:
        return TimeInForce[token]  # type: ignore[index]
    except (KeyError, TypeError, AttributeError):
        return TimeInForce(tif.lower())


def build_market_order(
    symbol: str,
    qty: int,
    side: str,
    tif: str = "DAY",
    client_order_id: Optional[str] = None,
) -> MarketOrderRequest:
    """Construct a basic market order request."""

    return MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=_normalise_side(side),
        time_in_force=_normalise_tif(tif),
        client_order_id=client_order_id,
    )


def _require_limit_price(limit_price: Optional[float]) -> float:
    if limit_price is None:
        raise ValueError("limit orders require a limit_price")
    return float(limit_price)


def build_limit_order(
    symbol: str,
    qty: int,
    side: str,
    limit_price: Optional[float],
    tif: str = "DAY",
    client_order_id: Optional[str] = None,
) -> LimitOrderRequest:
    """Construct a plain limit order request with validation."""

    price = _require_limit_price(limit_price)
    return LimitOrderRequest(
        symbol=symbol,
        qty=qty,
        side=_normalise_side(side),
        time_in_force=_normalise_tif(tif),
        limit_price=price,
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
) -> MarketOrderRequest:
    """Construct a market order with bracket exits."""

    return MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=_normalise_side(side),
        time_in_force=_normalise_tif(tif),
        order_class=OrderClass.BRACKET,
        take_profit=TakeProfitRequest(limit_price=float(take_profit_limit)),
        stop_loss=StopLossRequest(stop_price=float(stop_loss)),
        client_order_id=client_order_id,
    )


def build_bracket_limit_order(
    symbol: str,
    qty: int,
    side: str,
    limit_price: Optional[float],
    take_profit_limit: float,
    stop_loss: float,
    tif: str = "GTC",
    client_order_id: Optional[str] = None,
) -> LimitOrderRequest:
    """Construct a limit order with bracket exits, enforcing limit price."""

    price = _require_limit_price(limit_price)
    return LimitOrderRequest(
        symbol=symbol,
        qty=qty,
        side=_normalise_side(side),
        time_in_force=_normalise_tif(tif),
        order_class=OrderClass.BRACKET,
        limit_price=price,
        take_profit=TakeProfitRequest(limit_price=float(take_profit_limit)),
        stop_loss=StopLossRequest(stop_price=float(stop_loss)),
        client_order_id=client_order_id,
    )


__all__ = [
    "submit_order_sync",
    "submit_order_async",
    "build_market_order",
    "build_limit_order",
    "build_bracket_market_order",
    "build_bracket_limit_order",
]
