from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


@dataclass(frozen=True)
class RuntimeFlags:
    mock_mode: bool
    paper_trading: bool
    auto_restart: bool
    api_base_url: str
    alpaca_base_url: str
    alpaca_key: str | None
    alpaca_secret: str | None

    @staticmethod
    def from_env() -> "RuntimeFlags":
        mock_mode = parse_bool(os.getenv("MOCK_MODE"))
        paper = parse_bool(os.getenv("PAPER"), default=True)
        auto_restart = parse_bool(os.getenv("AUTO_RESTART"), default=True)
        api_base = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
        alpaca_key = os.getenv("ALPACA_API_KEY_ID") or os.getenv("APCA_API_KEY_ID")
        alpaca_secret = os.getenv("ALPACA_API_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")
        alpaca_base = "https://paper-api.alpaca.markets" if paper else "https://api.alpaca.markets"
        custom_alpaca_base = os.getenv("APCA_API_BASE_URL") or os.getenv("ALPACA_BASE_URL")
        if custom_alpaca_base:
            custom_alpaca_base = custom_alpaca_base.rstrip("/")
            if custom_alpaca_base:
                alpaca_base = custom_alpaca_base
        return RuntimeFlags(
            mock_mode=mock_mode,
            paper_trading=paper,
            auto_restart=auto_restart,
            api_base_url=api_base,
            alpaca_base_url=alpaca_base,
            alpaca_key=alpaca_key,
            alpaca_secret=alpaca_secret,
        )


@lru_cache(maxsize=1)
def get_runtime_flags() -> RuntimeFlags:
    return RuntimeFlags.from_env()
