"""Configuration management utilities."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Literal

import yaml
from pydantic import BaseModel, BaseSettings, Field, validator


class AlpacaSettings(BaseSettings):
    """Alpaca credentials sourced from environment variables."""

    key_id: str = Field("", env="ALPACA_KEY_ID")
    secret_key: str = Field("", env="ALPACA_SECRET_KEY")
    paper_endpoint: str = Field("https://paper-api.alpaca.markets", env="ALPACA_PAPER_ENDPOINT")
    live_endpoint: str = Field("https://api.alpaca.markets", env="ALPACA_LIVE_ENDPOINT")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


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


def load_config(path: Path) -> AppConfig:
    """Load configuration from ``path``."""

    with path.open("r", encoding="utf-8") as handle:
        payload: Dict[str, Any] = yaml.safe_load(handle)
    presets = {
        name: RiskPresetConfig(name=name, **cfg)
        for name, cfg in payload.get("risk_presets", {}).items()
    }
    payload["risk_presets"] = presets
    return AppConfig(**payload)


def get_alpaca_settings() -> AlpacaSettings:
    """Return Alpaca credentials from environment variables."""

    return AlpacaSettings()
