from __future__ import annotations

import os
from pydantic import BaseModel, Field

from core.runtime_flags import get_runtime_flags


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def _flags():
    return get_runtime_flags()


class AlpacaConfig(BaseModel):
    base_url: str = Field(default_factory=lambda: _flags().alpaca_base_url)
    key_id: str = Field(
        default_factory=lambda: _flags().alpaca_key
        or _env("ALPACA_KEY_ID", "ALPACA_API_KEY_ID", "APCA_API_KEY_ID")
    )
    secret_key: str = Field(
        default_factory=lambda: _flags().alpaca_secret
        or _env("ALPACA_SECRET_KEY", "ALPACA_API_SECRET_KEY", "APCA_API_SECRET_KEY")
    )
    data_feed: str = Field(default_factory=lambda: _env("ALPACA_DATA_FEED", default="iex"))
    data_ws_url: str = Field(
        default_factory=lambda: _env(
            "ALPACA_DATA_WS_URL",
            default="wss://stream.data.alpaca.markets/v2/iex",
        )
    )


def is_mock() -> bool:
    env_value = os.getenv("MOCK_MODE")
    if env_value is not None:
        if env_value.strip().lower() in {"1", "true", "yes", "on"}:
            return True
        if env_value.strip().lower() in {"0", "false", "no", "off"}:
            return False
    return _flags().mock_mode


def is_paper() -> bool:
    flags = _flags()
    return flags.paper_trading and not flags.mock_mode
