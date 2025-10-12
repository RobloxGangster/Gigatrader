from __future__ import annotations

import os

try:  # pragma: no cover - optional dependency for live entitlements
    from alpaca.common.exceptions import APIError
    from alpaca.data import StockHistoricalDataClient
    from alpaca.data.enums import DataFeed
    from alpaca.data.requests import StockLatestTradeRequest
except ModuleNotFoundError:  # pragma: no cover - offline fallback
    class APIError(Exception):
        """Fallback API error when alpaca-py is unavailable."""

    class DataFeed:
        SIP = "sip"

    class StockLatestTradeRequest:  # type: ignore[override]
        def __init__(self, symbol_or_symbols: str, feed: str) -> None:
            self.symbol_or_symbols = symbol_or_symbols
            self.feed = feed

    class StockHistoricalDataClient:  # type: ignore[override]
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def get_stock_latest_trade(self, *_args: object, **_kwargs: object) -> None:
            raise APIError("alpaca-py is not installed; SIP entitlement unavailable")


def sip_entitled(symbol: str = "SPY") -> bool:
    key, sec = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_API_SECRET")
    if not key or not sec:
        return False
    client = StockHistoricalDataClient(key, sec)
    try:
        client.get_stock_latest_trade(
            StockLatestTradeRequest(symbol_or_symbols=symbol, feed=DataFeed.SIP)
        )
        return True
    except APIError:
        return False
    except Exception:
        return False
