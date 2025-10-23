from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal


_FALSEY = {"0", "false", "no", "off", "f", "n"}
_TRUEY = {"1", "true", "yes", "on", "t", "y"}


def parse_bool(value: object | None, default: bool = False) -> bool:
    """Coerce user-provided strings and booleans into a boolean.

    The helper treats common truthy and falsey string representations in a
    case-insensitive manner and gracefully falls back to ``default`` when the
    input cannot be interpreted.
    """

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip()
    if not text:
        return default
    lowered = text.lower()
    if lowered in _TRUEY:
        return True
    if lowered in _FALSEY:
        return False
    return default


Broker = Literal["alpaca", "mock"]


def _coerce_int(value: object | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _sanitize_url(value: str | None, *, default: str) -> str:
    candidate = (value or default).strip()
    if not candidate:
        return default.rstrip("/")
    return candidate.rstrip("/")


def _determine_paper_mode(base_url: str) -> bool:
    lowered = base_url.lower()
    if "paper-api.alpaca.markets" in lowered:
        return True
    if "api.alpaca.markets" in lowered and "paper" not in lowered:
        return False
    env_override = os.getenv("ALPACA_PAPER")
    return parse_bool(env_override, default=True)


@dataclass(frozen=True)
class RuntimeFlags:
    mock_mode: bool
    broker: Broker
    dry_run: bool
    auto_restart: bool
    paper_trading: bool
    api_base_url: str
    api_port: int
    ui_port: int
    alpaca_base_url: str
    alpaca_key: str | None
    alpaca_secret: str | None

    @property
    def broker_mode(self) -> Literal["mock", "paper", "live"]:
        if self.mock_mode:
            return "mock"
        return "paper" if self.paper_trading else "live"

    @staticmethod
    def from_env() -> "RuntimeFlags":
        mock_mode = parse_bool(os.getenv("MOCK_MODE"))
        dry_run = parse_bool(os.getenv("DRY_RUN"))

        broker_env = os.getenv("BROKER", "").strip().lower()
        broker: Broker = "mock" if mock_mode else "alpaca"
        if broker_env in {"mock", "alpaca"}:
            broker = "mock" if broker_env == "mock" else "alpaca"
            if broker == "mock":
                mock_mode = True

        api_base = _sanitize_url(
            os.getenv("API_BASE") or os.getenv("API_BASE_URL"),
            default="http://127.0.0.1:8000",
        )
        api_port = _coerce_int(os.getenv("API_PORT"), 8000)
        ui_port = _coerce_int(os.getenv("UI_PORT"), 8501)

        env_base = os.getenv("ALPACA_BASE_URL") or os.getenv("APCA_API_BASE_URL")
        alpaca_base = _sanitize_url(
            env_base,
            default="https://paper-api.alpaca.markets",
        )
        paper = _determine_paper_mode(alpaca_base)

        trading_mode = os.getenv("TRADING_MODE", "").strip().lower()
        if trading_mode == "live":
            paper = False
        elif trading_mode == "paper":
            paper = True

        alpaca_key = os.getenv("ALPACA_KEY_ID") or os.getenv("ALPACA_API_KEY_ID")
        if not alpaca_key:
            alpaca_key = os.getenv("APCA_API_KEY_ID") or os.getenv("ALPACA_API_KEY")

        alpaca_secret = os.getenv("ALPACA_SECRET_KEY") or os.getenv("ALPACA_API_SECRET_KEY")
        if not alpaca_secret:
            alpaca_secret = os.getenv("APCA_API_SECRET_KEY") or os.getenv("ALPACA_API_SECRET")

        auto_restart = parse_bool(os.getenv("AUTO_RESTART"), default=True)

        return RuntimeFlags(
            mock_mode=mock_mode,
            broker=broker,
            dry_run=dry_run,
            auto_restart=auto_restart,
            paper_trading=paper,
            api_base_url=api_base,
            api_port=api_port,
            ui_port=ui_port,
            alpaca_base_url=alpaca_base,
            alpaca_key=alpaca_key,
            alpaca_secret=alpaca_secret,
        )


def require_alpaca_keys() -> None:
    missing = []
    key_id = os.getenv("ALPACA_KEY_ID")
    secret = os.getenv("ALPACA_SECRET_KEY")
    base_url = os.getenv("ALPACA_BASE_URL")
    if not key_id:
        missing.append("ALPACA_KEY_ID")
    if not secret:
        missing.append("ALPACA_SECRET_KEY")
    if not base_url or not re.match(r"https?://", base_url.strip()):
        missing.append("ALPACA_BASE_URL")
    if missing:
        joined = ", ".join(missing)
        raise ValueError(
            "Missing required Alpaca configuration: "
            f"{joined}. Please export the variables before starting the backend."
        )


@lru_cache(maxsize=1)
def _get_runtime_flags_cached() -> RuntimeFlags:
    return RuntimeFlags.from_env()


def get_runtime_flags() -> RuntimeFlags:
    if parse_bool(os.getenv("GIGATRADER_DISABLE_RUNTIME_FLAGS_CACHE")):
        return RuntimeFlags.from_env()
    return _get_runtime_flags_cached()


get_runtime_flags.cache_clear = _get_runtime_flags_cached.cache_clear  # type: ignore[attr-defined]


def refresh_runtime_flags() -> RuntimeFlags:
    _get_runtime_flags_cached.cache_clear()  # type: ignore[attr-defined]
    return _get_runtime_flags_cached()


__all__ = [
    "Broker",
    "RuntimeFlags",
    "get_runtime_flags",
    "parse_bool",
    "refresh_runtime_flags",
    "require_alpaca_keys",
]
