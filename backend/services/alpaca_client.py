from __future__ import annotations

import os
from functools import lru_cache

from alpaca.trading.client import TradingClient


def _bool_env(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    return default if v is None else str(v).strip().lower() in ("1", "true", "yes", "on")


@lru_cache(maxsize=1)
def get_trading_client() -> TradingClient:
    key = os.getenv("ALPACA_API_KEY_ID") or ""
    sec = os.getenv("ALPACA_API_SECRET_KEY") or ""
    paper = _bool_env("MOCK_MODE", False) is False and (
        "paper" in (os.getenv("APCA_API_BASE_URL") or "").lower()
    )
    # If MOCK_MODE=true, we *won't* call Alpaca at all; caller should gate on MOCK_MODE.
    # When paper mode is requested, set paper=True explicitly.
    return TradingClient(api_key=key, secret_key=sec, paper=paper)
