from __future__ import annotations

import os
import re
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field


load_dotenv()

_FALSEY = {"0", "false", "no", "off", "f", "n"}
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
        return default
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
        return "paper" if self.paper_trading else "live"


def runtime_flags_from_env() -> RuntimeFlags:
    """Build :class:`RuntimeFlags` from the current process environment."""

    def _parse_bool(name: str, default: bool) -> bool:
        raw = os.getenv(name)
        if raw is None:
            return default
        return raw.strip().lower() in {"1", "true", "yes", "y", "on"}

    broker = os.getenv("BROKER", "alpaca").strip() or "alpaca"
    profile = os.getenv("PROFILE", "paper").strip() or "paper"
    mock_mode = _parse_bool("MOCK_MODE", False)
    dry_run = _parse_bool("DRY_RUN", False)

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
    if mock_mode or lowered == "mock":
        broker_normalized = "mock"
        mock_mode = True
    elif lowered == "alpaca":
        broker_normalized = "alpaca"

    return RuntimeFlags(
        broker=broker_normalized,
        profile=profile,
        mock_mode=mock_mode,
        dry_run=dry_run,
        auto_restart=auto_restart,
        paper_trading=paper_trading,
        api_base_url=api_base,
        api_port=api_port,
        ui_port=ui_port,
        alpaca_base_url=alpaca_base,
        alpaca_key=alpaca_key,
        alpaca_secret=alpaca_secret,
    )


def get_runtime_flags() -> RuntimeFlags:
    return runtime_flags_from_env()


def refresh_runtime_flags() -> RuntimeFlags:
    return runtime_flags_from_env()


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


__all__ = [
    "Broker",
    "RuntimeFlags",
    "get_runtime_flags",
    "parse_bool",
    "refresh_runtime_flags",
    "require_alpaca_keys",
    "runtime_flags_from_env",
]
