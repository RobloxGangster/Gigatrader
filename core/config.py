"""Configuration management utilities."""

from __future__ import annotations

# --- .env bootstrap ---
try:
    from dotenv import load_dotenv  # python-dotenv

    load_dotenv()
except Exception:
    pass

# --- pydantic settings requirement (v2) ---
try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError as e:
    raise RuntimeError(
        "Missing dependency 'pydantic-settings'. "
        "Install it via: pip install 'pydantic-settings>=2.2,<3'"
    ) from e

from pathlib import Path
from typing import Any, Dict, Literal

try:  # pragma: no cover - import guard exercised indirectly
    import yaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - executed in minimal environments
    yaml = None
    import json

from pydantic import BaseModel, Field, field_validator


class AlpacaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    api_key_id: str = Field(default="", env="ALPACA_API_KEY_ID")
    api_secret_key: str = Field(default="", env="ALPACA_API_SECRET_KEY")
    base_url: str = Field(default="https://paper-api.alpaca.markets", env="APCA_API_BASE_URL")
    paper: bool = True
    request_timeout_s: float = 10.0
    max_retries: int = 3
    retry_backoff_s: float = 0.75


class OrderDefaults(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    tif: str = Field(default="day", env="DEFAULT_TIF")
    allow_brackets: bool = Field(default=True, env="ALLOW_BRACKETS")
    default_tp_pct: float = Field(default=0.01, env="DEFAULT_TP_PCT")
    default_sl_pct: float = Field(default=0.005, env="DEFAULT_SL_PCT")


_alpaca = AlpacaSettings()
_orders = OrderDefaults()


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

    @field_validator("profile", mode="before")
    @classmethod
    def validate_live_profile(cls, value: str) -> str:
        if value is None:
            return value

        str_value = str(value)

        if str_value == "live":
            from os import getenv

            if getenv("LIVE_TRADING", "false").lower() != "true":
                raise ValueError("LIVE_TRADING env flag must be true for live profile")
        return str_value


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
    """Return cached Alpaca configuration settings."""

    return _alpaca


def get_order_defaults() -> OrderDefaults:
    """Return global order defaults used by the execution layer."""

    return _orders


def masked_key_tail(k: str | None) -> str | None:
    """Return the last 4 characters of a credential for safe logging."""

    return k[-4:] if k else None
