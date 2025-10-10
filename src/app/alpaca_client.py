from __future__ import annotations

import os

from alpaca.trading.client import TradingClient


def build_trading_client() -> TradingClient:
    key = os.getenv("ALPACA_API_KEY")
    sec = os.getenv("ALPACA_API_SECRET")
    if not key or not sec:
        raise RuntimeError("Missing ALPACA_API_KEY / ALPACA_API_SECRET.")
    live = os.getenv("LIVE_TRADING", "").lower() == "true"
    return TradingClient(key, sec, paper=not live)
