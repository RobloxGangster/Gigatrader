from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


BrokerMode = Literal["mock", "paper", "live"]


def _coerce_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_broker_mode(value: str | None) -> BrokerMode | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"paper", "live", "mock"}:
        return normalized  # type: ignore[return-value]
    return None


@dataclass(frozen=True)
class RuntimeFlags:
    mock_mode: bool
    broker_mode: BrokerMode
    paper_trading: bool
    auto_restart: bool
    api_base_url: str
    api_port: int
    ui_port: int
    alpaca_base_url: str
    alpaca_key: str | None
    alpaca_secret: str | None

    @staticmethod
    def from_env() -> "RuntimeFlags":
        broker_mode_env = _normalize_broker_mode(os.getenv("BROKER_MODE"))
        if broker_mode_env is None:
            # legacy compatibility – honour MOCK_MODE first
            if parse_bool(os.getenv("MOCK_MODE")):
                broker_mode_env = "mock"
            else:
                trading_mode = os.getenv("TRADING_MODE", "paper").strip().lower()
                if trading_mode == "live":
                    broker_mode_env = "live"
                else:
                    broker_mode_env = "paper"

        mock_mode = broker_mode_env == "mock"
        paper = broker_mode_env != "live"
        auto_restart = parse_bool(os.getenv("AUTO_RESTART"), default=True)
        api_base = (
            os.getenv("API_BASE")
            or os.getenv("API_BASE_URL")
            or "http://127.0.0.1:8000"
        ).rstrip("/")
        api_port = _coerce_int(os.getenv("API_PORT"), 8000)
        ui_port = _coerce_int(os.getenv("UI_PORT"), 8501)

        paper_base = (
            os.getenv("ALPACA_PAPER_BASE")
            or os.getenv("APCA_API_BASE_URL")
            or os.getenv("ALPACA_BASE_URL")
            or "https://paper-api.alpaca.markets"
        ).rstrip("/")
        live_base = (
            os.getenv("ALPACA_LIVE_BASE")
            or os.getenv("ALPACA_BASE_URL_LIVE")
            or "https://api.alpaca.markets"
        ).rstrip("/")

        alpaca_base = paper_base if broker_mode_env != "live" else live_base
        custom_alpaca_base = os.getenv("ALPACA_BASE_URL")
        if custom_alpaca_base:
            custom_alpaca_base = custom_alpaca_base.rstrip("/")
            if custom_alpaca_base:
                alpaca_base = custom_alpaca_base
        if broker_mode_env == "mock":
            # Keep using paper endpoints to avoid surprises when toggling modes.
            alpaca_base = paper_base

        alpaca_key = (
            os.getenv("ALPACA_API_KEY")
            or os.getenv("ALPACA_API_KEY_ID")
            or os.getenv("APCA_API_KEY_ID")
        )
        alpaca_secret = (
            os.getenv("ALPACA_API_SECRET")
            or os.getenv("ALPACA_API_SECRET_KEY")
            or os.getenv("APCA_API_SECRET_KEY")
        )
        return RuntimeFlags(
            mock_mode=mock_mode,
            broker_mode=broker_mode_env,
            paper_trading=paper,
            auto_restart=auto_restart,
            api_base_url=api_base,
            api_port=api_port,
            ui_port=ui_port,
            alpaca_base_url=alpaca_base,
            alpaca_key=alpaca_key,
            alpaca_secret=alpaca_secret,
        )


@lru_cache(maxsize=1)
def get_runtime_flags() -> RuntimeFlags:
    return RuntimeFlags.from_env()
