from __future__ import annotations

import os
from functools import lru_cache

from alpaca.trading.client import TradingClient

from core.broker_config import AlpacaConfig, is_mock


def _bool_env(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    return default if v is None else str(v).strip().lower() in ("1", "true", "yes", "on")


@lru_cache(maxsize=1)
def get_trading_client() -> TradingClient:
    cfg = AlpacaConfig()
    key = cfg.key_id or os.getenv("ALPACA_API_KEY_ID") or ""
    sec = cfg.secret_key or os.getenv("ALPACA_API_SECRET_KEY") or ""
    base_url = cfg.base_url or os.getenv("APCA_API_BASE_URL") or "https://paper-api.alpaca.markets"
    os.environ["APCA_API_BASE_URL"] = base_url
    paper = (not is_mock()) and ("paper" in base_url.lower())
    # If MOCK_MODE=true, callers should gate off before invoking this helper.
    return TradingClient(api_key=key, secret_key=sec, paper=paper)
