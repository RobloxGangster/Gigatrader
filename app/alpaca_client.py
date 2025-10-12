from __future__ import annotations

import os

from alpaca.trading.client import TradingClient


def build_trading_client() -> TradingClient:
    key = os.getenv("ALPACA_API_KEY_ID") or os.getenv("ALPACA_API_KEY")
    sec = os.getenv("ALPACA_API_SECRET_KEY") or os.getenv("ALPACA_API_SECRET")
    if not key or not sec:
        raise RuntimeError("Missing ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY.")
    live = os.getenv("TRADING_MODE", "paper").lower() == "live"
    paper = not live or os.getenv("ALPACA_PAPER", "true").lower() in {"1", "true", "yes", "on"}
    return TradingClient(key, sec, paper=paper)
