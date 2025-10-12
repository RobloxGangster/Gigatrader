"""Configuration management utilities."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Literal

try:  # pragma: no cover - import guard exercised indirectly
    import yaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - executed in minimal environments
    yaml = None
    import json

from pydantic import BaseModel, Field, validator


@dataclass(slots=True)
class AlpacaSettings:
    """Alpaca credentials sourced from environment variables."""

    key_id: str = ""
    secret_key: str = ""
    paper_endpoint: str = "https://paper-api.alpaca.markets"
    live_endpoint: str = "https://api.alpaca.markets"

    @classmethod
    def from_env(cls) -> "AlpacaSettings":
        key_id = (
            os.getenv("ALPACA_KEY_ID")
            or os.getenv("ALPACA_API_KEY")
            or os.getenv("APCA_API_KEY_ID")
            or ""
        )
        secret_key = (
            os.getenv("ALPACA_SECRET_KEY")
            or os.getenv("ALPACA_API_SECRET")
            or os.getenv("APCA_API_SECRET_KEY")
            or ""
        )
        paper_endpoint = os.getenv(
            "ALPACA_PAPER_ENDPOINT",
            os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
        )
        live_endpoint = os.getenv(
            "ALPACA_LIVE_ENDPOINT", os.getenv("APCA_API_BASE_URL", "https://api.alpaca.markets")
        )

        return cls(
            key_id=key_id,
            secret_key=secret_key,
            paper_endpoint=paper_endpoint,
            live_endpoint=live_endpoint,
        )


class RiskPresetConfig(BaseModel):
    name: Literal["safe", "balanced", "high_risk"]
    daily_loss_limit: float
    per_trade_loss_limit: float
    max_exposure: float
    max_positions: int
    options_max_notional_per_expiry: float
    min_option_liquidity: int
    delta_bounds: tuple[float, float]
    vega_limit: float
    theta_limit: float


class ExecutionConfig(BaseModel):
    venue: str
    time_in_force: str
    allow_extended_hours: bool = False
    default_bracket: Dict[str, Any] = Field(default_factory=dict)


class DataConfig(BaseModel):
    symbols: list[str]
    timeframes: list[str]
    cache_path: Path


class AppConfig(BaseModel):
    profile: Literal["paper", "live"] = "paper"
    data: DataConfig
    execution: ExecutionConfig
    risk_profile: Literal["safe", "balanced", "high_risk"] = "safe"
    risk_presets: Dict[str, RiskPresetConfig]

    @validator("profile")
    def validate_live_profile(cls, value: str) -> str:
        if value == "live":
            from os import getenv

            if getenv("LIVE_TRADING", "false").lower() != "true":
                raise ValueError("LIVE_TRADING env flag must be true for live profile")
        return value


def _read_config_payload(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if yaml is not None:  # pragma: no branch - trivial check
        return yaml.safe_load(text)
    return json.loads(text)


def load_config(path: Path) -> AppConfig:
    """Load configuration from ``path``."""

    payload = _read_config_payload(path)
    presets = {}
    for name, cfg in payload.get("risk_presets", {}).items():
        preset_payload = dict(cfg)
        preset_payload.setdefault("name", name)
        presets[name] = RiskPresetConfig(**preset_payload)
    payload["risk_presets"] = presets
    return AppConfig(**payload)


def get_alpaca_settings() -> AlpacaSettings:
    """Return Alpaca credentials from environment variables."""

    return AlpacaSettings.from_env()
