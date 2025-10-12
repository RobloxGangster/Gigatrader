from __future__ import annotations

import os

from alpaca.common.exceptions import APIError
from alpaca.data import StockHistoricalDataClient
from alpaca.data.enums import DataFeed
from alpaca.data.requests import StockLatestTradeRequest


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
