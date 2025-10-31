"""Configuration management for the trading app."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List


def _env_pick(*names: str, default: str | None = None) -> str | None:
    """Return the first non-empty environment variable in *names*."""

    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    alpaca_key_id: str
    alpaca_secret_key: str
    alpaca_base_url: str | None
    paper: bool
    data_feed: str
    smoke_symbols: List[str]
    smoke_timeframe: str


def get_settings() -> Settings:
    """Load application settings from the environment."""

    key = _env_pick("ALPACA_KEY_ID", "ALPACA_API_KEY_ID", "ALPACA_API_KEY", default="") or ""
    secret = _env_pick(
        "ALPACA_SECRET_KEY",
        "ALPACA_API_SECRET_KEY",
        "ALPACA_API_SECRET",
        default="",
    ) or ""
    base_url = _env_pick("ALPACA_BASE_URL")
    if not key or not secret:
        raise RuntimeError(
            "Missing ALPACA_API_KEY_ID/ALPACA_API_KEY or "
            "ALPACA_API_SECRET_KEY/ALPACA_API_SECRET in environment."
        )

    paper_requested = _bool("ALPACA_PAPER", True)
    trading_mode = os.getenv("TRADING_MODE", "paper").lower()
    live_flag = os.getenv("LIVE_TRADING", "false").lower() == "true"
    live_requested = trading_mode == "live" or not paper_requested
    if live_requested and not live_flag:
        raise RuntimeError(
            "Refusing to enable live trading without LIVE_TRADING=true."
        )
    paper = not live_requested
    data_feed = os.getenv("ALPACA_DATA_FEED", "iex").lower()
    symbols = [
        s.strip().upper()
        for s in os.getenv("SMOKE_SYMBOLS", "AAPL,MSFT,SPY").split(",")
        if s.strip()
    ]
    timeframe = os.getenv("SMOKE_TIMEFRAME", "1Min")

    return Settings(
        alpaca_key_id=key,
        alpaca_secret_key=secret,
        alpaca_base_url=base_url,
        paper=paper,
        data_feed=data_feed,
        smoke_symbols=symbols,
        smoke_timeframe=timeframe,
    )
