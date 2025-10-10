from __future__ import annotations

import os
from typing import Optional

try:  # pragma: no cover - exercised indirectly via tests
    from alpaca.common.exceptions import APIError
    from alpaca.data import StockHistoricalDataClient
    from alpaca.data.enums import DataFeed
    from alpaca.data.requests import StockLatestTradeRequest
except ModuleNotFoundError:  # pragma: no cover - gracefully degrade when alpaca-py absent
    APIError = Exception  # type: ignore
    StockHistoricalDataClient = None  # type: ignore
    DataFeed = None  # type: ignore
    StockLatestTradeRequest = None  # type: ignore


def _get_credentials() -> tuple[Optional[str], Optional[str]]:
    key = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
    secret = os.getenv("ALPACA_API_SECRET") or os.getenv("APCA_API_SECRET_KEY")
    if not key:
        key = os.getenv("ALPACA_KEY_ID")
    if not secret:
        secret = os.getenv("ALPACA_SECRET_KEY")
    return key, secret


def sip_entitled(symbol: str = "SPY") -> bool:
    key, secret = _get_credentials()
    if not key or not secret:
        return False
    if StockHistoricalDataClient is None or StockLatestTradeRequest is None or DataFeed is None:
        return False

    client = StockHistoricalDataClient(key, secret)
    try:
        request = StockLatestTradeRequest(symbol_or_symbols=symbol, feed=DataFeed.SIP)
        client.get_stock_latest_trade(request)
        return True
    except APIError:
        return False
    except Exception:
        return False
