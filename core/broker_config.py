from __future__ import annotations

import os
from pydantic import BaseModel, Field


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


class AlpacaConfig(BaseModel):
    base_url: str = Field(
        default_factory=lambda: _env(
            "ALPACA_BASE_URL", "APCA_API_BASE_URL", default="https://paper-api.alpaca.markets"
        )
    )
    key_id: str = Field(
        default_factory=lambda: _env("ALPACA_KEY_ID", "ALPACA_API_KEY_ID", "APCA_API_KEY_ID")
    )
    secret_key: str = Field(
        default_factory=lambda: _env(
            "ALPACA_SECRET_KEY", "ALPACA_API_SECRET_KEY", "APCA_API_SECRET_KEY"
        )
    )
    data_feed: str = Field(default_factory=lambda: _env("ALPACA_DATA_FEED", default="iex"))
    data_ws_url: str = Field(
        default_factory=lambda: _env(
            "ALPACA_DATA_WS_URL",
            default="wss://stream.data.alpaca.markets/v2/iex",
        )
    )


def is_mock() -> bool:
    return os.getenv("MOCK_MODE", "false").lower() == "true"


def is_paper() -> bool:
    return os.getenv("RUN_MODE", "paper").lower() == "paper"
