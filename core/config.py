"""Configuration management utilities."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Literal, Optional

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError as e:  # pragma: no cover - dependency guard
    raise RuntimeError(
        "Missing dependency 'pydantic-settings'. Install with: pip install 'pydantic-settings>=2.2,<3'"
    ) from e

try:  # pragma: no cover - import guard exercised indirectly
    import yaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - executed in minimal environments
    yaml = None
    import json

from dataclasses import dataclass, field, asdict

from pydantic import BaseModel, Field, field_validator

from core.runtime_flags import get_runtime_flags


_FLAGS = get_runtime_flags()

MOCK_MODE = _FLAGS.mock_mode




class OrderDefaults(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    tif: str = Field(default="day", env="DEFAULT_TIF")
    allow_brackets: bool = Field(default=True, env="ALLOW_BRACKETS")
    default_tp_pct: float = Field(default=0.01, env="DEFAULT_TP_PCT")
    default_sl_pct: float = Field(default=0.005, env="DEFAULT_SL_PCT")


@dataclass(slots=True)
class AlpacaSettings:
    api_key: str | None
    api_secret: str | None
    base_url: str
    paper: bool


@dataclass(slots=True)
class TradeLoopConfig:
    """Runtime configuration for the live trading loop."""

    interval_sec: float = 10.0
    top_n: int = 3
    min_conf: float = 0.55
    min_ev: float = 0.0
    universe: list[str] = field(default_factory=lambda: ["AAPL", "MSFT", "NVDA"])
    profile: str = "balanced"
    duplicate_retry_attempts: int = 1

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["universe"] = list(self.universe)
        return payload

    def with_overrides(self, **overrides: object) -> "TradeLoopConfig":
        payload = self.to_dict()
        for key, value in overrides.items():
            if value is None:
                continue
            if key == "universe":
                if isinstance(value, str):
                    payload[key] = [value]
                else:
                    payload[key] = list(value)  # type: ignore[arg-type]
            else:
                payload[key] = value
        return TradeLoopConfig(**payload)


@dataclass(slots=True)
class AuditConfig:
    audit_dir: Path = Path("data/logs")
    audit_file: str = "trade_audit.ndjson"
    reconcile_state_file: str = "orders_state.json"

    def audit_path(self) -> Path:
        base = self.audit_dir if isinstance(self.audit_dir, Path) else Path(self.audit_dir)
        return base / self.audit_file

    def state_path(self) -> Path:
        base = self.audit_dir if isinstance(self.audit_dir, Path) else Path(self.audit_dir)
        return base / self.reconcile_state_file


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
    flags = get_runtime_flags()
    return AlpacaSettings(
        api_key=flags.alpaca_key,
        api_secret=flags.alpaca_secret,
        base_url=flags.alpaca_base_url,
        paper=flags.paper_trading,
    )


def get_order_defaults() -> OrderDefaults:
    """Instantiate order defaults from the environment."""

    return OrderDefaults()


def get_audit_config() -> AuditConfig:
    """Return audit logging configuration."""

    return AuditConfig()


def alpaca_config_ok() -> bool:
    s = get_alpaca_settings()
    return bool(s.api_key and s.api_secret)


def masked_tail(s: Optional[str]) -> Optional[str]:
    return s[-4:] if s else None


def resolved_env_sources() -> Dict[str, bool]:
    import os

    def _has(k: str) -> bool:
        v = os.environ.get(k)
        return bool(v and str(v).strip())

    return {
        "ALPACA_API_KEY_ID": _has("ALPACA_API_KEY_ID"),
        "APCA_API_KEY_ID": _has("APCA_API_KEY_ID"),
        "ALPACA_API_SECRET_KEY": _has("ALPACA_API_SECRET_KEY"),
        "APCA_API_SECRET_KEY": _has("APCA_API_SECRET_KEY"),
        "APCA_API_BASE_URL": _has("APCA_API_BASE_URL"),
        "ALPACA_API_BASE_URL": _has("ALPACA_API_BASE_URL"),
    }


def get_signal_defaults():
    from app.signals.signal_engine import SignalConfig

    return SignalConfig()





def debug_alpaca_snapshot() -> Dict[str, Any]:
    cfg = get_alpaca_settings()
    env_flags = resolved_env_sources()
    return {
        "configured": alpaca_config_ok(),
        "base_url": cfg.base_url or ("paper" if cfg.paper else "live"),
        "paper": cfg.paper,
        "key_tail": masked_tail(cfg.api_key),
        "env": env_flags,
    }
