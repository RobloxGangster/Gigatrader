from __future__ import annotations

import os
import re
import threading
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field


_FLAGS_CACHE: "RuntimeFlags | None" = None
_FLAGS_SIGNATURE: tuple[tuple[str, str | None], ...] | None = None
_CACHE_LOCK = threading.Lock()

_FALSEY = {"0", "false", "no", "off", "f", "n", ""}
_TRUEY = {"1", "true", "yes", "on", "t", "y"}


Broker = Literal["alpaca", "mock"]


def parse_bool(value: object | None, default: bool = False) -> bool:
    """Coerce user-provided strings and booleans into a boolean."""

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip()
    if not text:
        return False
    lowered = text.lower()
    if lowered in _TRUEY:
        return True
    if lowered in _FALSEY:
        return False
    return default


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
    use_paper_override = os.getenv("ALPACA_USE_PAPER")
    if use_paper_override is not None:
        return parse_bool(use_paper_override, default=True)
    lowered = base_url.lower()
    if "paper-api.alpaca.markets" in lowered:
        return True
    if "api.alpaca.markets" in lowered and "paper" not in lowered:
        return False
    env_override = os.getenv("ALPACA_PAPER")
    return parse_bool(env_override, default=True)


class RuntimeFlags(BaseModel):
    model_config = ConfigDict(frozen=True)

    broker: str = Field(default="alpaca")
    profile: str = Field(default="paper")
    mock_mode: bool = Field(default=False)
    dry_run: bool = Field(default=False)
    market_data_source: str = Field(default="alpaca")
    auto_restart: bool = Field(default=True)
    paper_trading: bool = Field(default=True)
    api_base_url: str = Field(default="http://127.0.0.1:8000")
    api_port: int = Field(default=8000)
    ui_port: int = Field(default=8501)
    alpaca_base_url: str = Field(default="https://paper-api.alpaca.markets")
    alpaca_key: str | None = Field(default=None)
    alpaca_secret: str | None = Field(default=None)

    @property
    def broker_mode(self) -> Literal["mock", "paper", "live"]:
        if self.mock_mode:
            return "mock"
        if str(self.broker).lower() == "alpaca":
            return "paper" if self.paper_trading else "live"
        return "mock"


_SIGNATURE_KEYS = (
    "BROKER",
    "PROFILE",
    "MOCK_MODE",
    "DRY_RUN",
    "MARKET_DATA_SOURCE",
    "API_BASE",
    "API_BASE_URL",
    "API_PORT",
    "UI_PORT",
    "ALPACA_BASE_URL",
    "APCA_API_BASE_URL",
    "ALPACA_KEY_ID",
    "ALPACA_API_KEY_ID",
    "APCA_API_KEY_ID",
    "ALPACA_SECRET_KEY",
    "ALPACA_API_SECRET_KEY",
    "APCA_API_SECRET_KEY",
    "ALPACA_API_KEY",
    "ALPACA_API_SECRET",
    "ALPACA_USE_PAPER",
    "AUTO_RESTART",
    "TRADING_MODE",
    "ALPACA_PAPER",
)


def _env_signature() -> tuple[tuple[str, str | None], ...]:
    return tuple((name, os.getenv(name)) for name in _SIGNATURE_KEYS)


def _build_runtime_flags() -> RuntimeFlags:
    """Internal helper to hydrate :class:`RuntimeFlags` from the environment."""

    load_dotenv(override=False)

    def _parse_bool(name: str, default: bool) -> bool:
        return parse_bool(os.getenv(name), default=default)

    broker = os.getenv("BROKER", "alpaca").strip() or "alpaca"
    profile = os.getenv("PROFILE", "paper").strip() or "paper"
    mock_mode = _parse_bool("MOCK_MODE", False)
    dry_run = _parse_bool("DRY_RUN", False)

    mds_env = os.getenv("MARKET_DATA_SOURCE")
    if mds_env:
        market_data_source = mds_env.strip().lower() or "mock"
    else:
        if mock_mode:
            market_data_source = "mock"
        elif broker.strip().lower() == "alpaca":
            market_data_source = "alpaca"
        else:
            market_data_source = "mock"

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

    paper_trading = _determine_paper_mode(alpaca_base)
    profile_lower = profile.lower()
    if profile_lower == "live":
        paper_trading = False
    elif profile_lower == "paper":
        paper_trading = True

    trading_mode = os.getenv("TRADING_MODE", "").strip().lower()
    if trading_mode == "live":
        paper_trading = False
    elif trading_mode == "paper":
        paper_trading = True

    alpaca_key = (
        os.getenv("ALPACA_KEY_ID")
        or os.getenv("ALPACA_API_KEY_ID")
        or os.getenv("APCA_API_KEY_ID")
        or os.getenv("ALPACA_API_KEY")
    )
    alpaca_secret = (
        os.getenv("ALPACA_SECRET_KEY")
        or os.getenv("ALPACA_API_SECRET_KEY")
        or os.getenv("APCA_API_SECRET_KEY")
        or os.getenv("ALPACA_API_SECRET")
    )

    auto_restart = parse_bool(os.getenv("AUTO_RESTART"), default=True)

    # Normalise broker setting – if mock_mode is forced we always report mock.
    broker_normalized: Broker = "alpaca"
    lowered = broker.lower()
    if lowered == "mock":
        broker_normalized = "mock"
    elif lowered == "alpaca":
        broker_normalized = "alpaca"

    if mds_env:
        market_data_source = mds_env.strip().lower() or market_data_source
    else:
        if mock_mode:
            market_data_source = "mock"
        elif broker_normalized == "alpaca":
            market_data_source = "alpaca"
        else:
            market_data_source = "mock"

    return RuntimeFlags(
        broker=broker_normalized,
        profile=profile,
        mock_mode=mock_mode,
        dry_run=dry_run,
        market_data_source=market_data_source,
        auto_restart=auto_restart,
        paper_trading=paper_trading,
        api_base_url=api_base,
        api_port=api_port,
        ui_port=ui_port,
        alpaca_base_url=alpaca_base,
        alpaca_key=alpaca_key,
        alpaca_secret=alpaca_secret,
    )


def runtime_flags_from_env() -> RuntimeFlags:
    """Build :class:`RuntimeFlags` from environment variables without caching."""

    return _build_runtime_flags()


def get_runtime_flags() -> RuntimeFlags:
    global _FLAGS_CACHE, _FLAGS_SIGNATURE
    signature = _env_signature()
    with _CACHE_LOCK:
        if _FLAGS_CACHE is None or signature != _FLAGS_SIGNATURE:
            _FLAGS_CACHE = _build_runtime_flags()
            _FLAGS_SIGNATURE = signature
        return _FLAGS_CACHE


def refresh_runtime_flags() -> RuntimeFlags:
    global _FLAGS_CACHE, _FLAGS_SIGNATURE
    with _CACHE_LOCK:
        _FLAGS_CACHE = _build_runtime_flags()
        _FLAGS_SIGNATURE = _env_signature()
        return _FLAGS_CACHE


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


def require_live_alpaca_or_fail() -> None:
    """Ensure live Alpaca credentials are present when live mode is requested."""

    mock_mode_env = parse_bool(os.getenv("MOCK_MODE"), default=False)
    if mock_mode_env:
        return

    missing: list[str] = []
    key_id = (
        os.getenv("ALPACA_KEY_ID")
        or os.getenv("ALPACA_API_KEY_ID")
        or os.getenv("APCA_API_KEY_ID")
    )
    secret_key = (
        os.getenv("ALPACA_SECRET_KEY")
        or os.getenv("ALPACA_API_SECRET_KEY")
        or os.getenv("APCA_API_SECRET_KEY")
    )
    base_url = (
        os.getenv("ALPACA_BASE_URL")
        or os.getenv("APCA_API_BASE_URL")
        or os.getenv("ALPACA_API_BASE_URL")
    )

    if not key_id:
        missing.append("ALPACA_KEY_ID")
    if not secret_key:
        missing.append("ALPACA_SECRET_KEY")
    if not base_url:
        missing.append("ALPACA_BASE_URL")

    if missing:
        joined = ", ".join(sorted(set(missing)))
        raise RuntimeError(
            "Live Alpaca paper mode requested (MOCK_MODE=false), but missing env: "
            f"{joined}"
        )


__all__ = [
    "Broker",
    "RuntimeFlags",
    "get_runtime_flags",
    "parse_bool",
    "refresh_runtime_flags",
    "require_live_alpaca_or_fail",
    "require_alpaca_keys",
    "runtime_flags_from_env",
]
