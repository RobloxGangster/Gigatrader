from __future__ import annotations

import os

from alpaca.trading.client import TradingClient


def _is_truthy(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "y", "on"}


def build_trading_client() -> TradingClient:
    key = os.getenv("ALPACA_API_KEY_ID") or os.getenv("ALPACA_API_KEY")
    sec = os.getenv("ALPACA_API_SECRET_KEY") or os.getenv("ALPACA_API_SECRET")
    if not key or not sec:
        raise RuntimeError("Missing ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY.")

    trading_mode = os.getenv("TRADING_MODE", "paper").lower()
    live_flag = os.getenv("LIVE_TRADING", "false").lower() == "true"

    paper_setting = os.getenv("ALPACA_PAPER")
    paper_requested = True if paper_setting is None else _is_truthy(paper_setting)
    live_requested = trading_mode == "live" or not paper_requested

    if live_requested and not live_flag:
        raise RuntimeError(
            "Refusing to run in live trading mode unless LIVE_TRADING=true."
        )

    paper = not live_requested
    return TradingClient(key, sec, paper=paper)
