"""Configuration management utilities."""

from __future__ import annotations

# Ensure .env is loaded early
try:
    from dotenv import load_dotenv  # python-dotenv

    load_dotenv()
except Exception:
    # optional dependency; safe to continue if not present
    pass

# Require pydantic-settings for Pydantic v2 configs
try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError as e:  # pragma: no cover - import guard exercised indirectly
    raise RuntimeError(
        "Missing dependency 'pydantic-settings'. "
        "Install with: pip install 'pydantic-settings>=2.2,<3'"
    ) from e

from pathlib import Path
from typing import Any, Dict, Literal

try:  # pragma: no cover - import guard exercised indirectly
    import yaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - executed in minimal environments
    yaml = None
    import json

from pydantic import AliasChoices, BaseModel, Field, field_validator


class AlpacaSettings(BaseSettings):
    """Credentials and runtime settings for the Alpaca Trading API."""

    model_config = SettingsConfigDict(env_prefix="")

    api_key_id: str = Field(
        default="",
        validation_alias=AliasChoices(
            "ALPACA_API_KEY_ID",
            "ALPACA_KEY_ID",
            "ALPACA_API_KEY",
            "APCA_API_KEY_ID",
        )
    )
    api_secret_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "ALPACA_API_SECRET_KEY",
            "ALPACA_SECRET_KEY",
            "ALPACA_API_SECRET",
            "APCA_API_SECRET_KEY",
        )
    )
    base_url: str = Field(
        default="https://paper-api.alpaca.markets",
        validation_alias=AliasChoices("APCA_API_BASE_URL", "ALPACA_BASE_URL", "ALPACA_PAPER_ENDPOINT"),
    )
    paper: bool = Field(default=True, validation_alias=AliasChoices("ALPACA_PAPER"))
    request_timeout_s: float = Field(default=10.0, validation_alias=AliasChoices("ALPACA_REQUEST_TIMEOUT"))
    max_retries: int = Field(default=3, validation_alias=AliasChoices("ALPACA_MAX_RETRIES"))
    retry_backoff_s: float = Field(default=0.75, validation_alias=AliasChoices("ALPACA_RETRY_BACKOFF"))


class OrderDefaults(BaseSettings):
    """Global defaults applied to order submission flows."""

    model_config = SettingsConfigDict(env_prefix="")

    tif: str = Field(default="day", validation_alias=AliasChoices("DEFAULT_TIF"))
    allow_brackets: bool = Field(default=True, validation_alias=AliasChoices("ALLOW_BRACKETS"))
    default_tp_pct: float = Field(default=0.01, validation_alias=AliasChoices("DEFAULT_TP_PCT"))
    default_sl_pct: float = Field(default=0.005, validation_alias=AliasChoices("DEFAULT_SL_PCT"))


alpaca_settings = AlpacaSettings()
order_defaults = OrderDefaults()


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

    return alpaca_settings


def get_order_defaults() -> OrderDefaults:
    """Return global order defaults used by the execution layer."""

    return order_defaults
