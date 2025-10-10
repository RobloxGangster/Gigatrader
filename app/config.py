"""Configuration management for the trading app."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List

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
    paper: bool
    data_feed: str
    smoke_symbols: List[str]
    smoke_timeframe: str


def get_settings() -> Settings:
    """Load application settings from the environment."""

    key = os.getenv("ALPACA_API_KEY_ID", "")
    secret = os.getenv("ALPACA_API_SECRET_KEY", "")
    if not key or not secret:
        raise RuntimeError("Missing ALPACA_API_KEY_ID or ALPACA_API_SECRET_KEY in environment.")

    paper = _bool("ALPACA_PAPER", True)
    data_feed = os.getenv("ALPACA_DATA_FEED", "iex").lower()
    symbols = [s.strip().upper() for s in os.getenv("SMOKE_SYMBOLS", "AAPL,MSFT,SPY").split(",") if s.strip()]
    timeframe = os.getenv("SMOKE_TIMEFRAME", "1Min")

    return Settings(
        alpaca_key_id=key,
        alpaca_secret_key=secret,
        paper=paper,
        data_feed=data_feed,
        smoke_symbols=symbols,
        smoke_timeframe=timeframe,
    )
