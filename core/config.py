"""Configuration management utilities."""

from __future__ import annotations

# --- Robust .env bootstrap (search repo root & parents) ---
import os
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Tuple

try:
    from dotenv import load_dotenv, find_dotenv  # python-dotenv

    # Try CWD (when launched from repo root)
    load_dotenv(find_dotenv(filename=".env", usecwd=True), override=False)

    # Also try alongside this file's repo root (…/Gigatrader/.env)
    ROOT = Path(__file__).resolve().parents[1]
    env_at_root = ROOT / ".env"
    if env_at_root.exists():
        load_dotenv(env_at_root, override=False)
except Exception:
    pass

# --- pydantic settings requirement (v2) ---
try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError as e:
    raise RuntimeError(
        "Missing dependency 'pydantic-settings'. Install with: pip install 'pydantic-settings>=2.2,<3'"
    ) from e
try:  # pragma: no cover - import guard exercised indirectly
    import yaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - executed in minimal environments
    yaml = None
    import json

from pydantic import BaseModel, Field, field_validator


def _getenv(name: str) -> Optional[str]:
    v = os.environ.get(name)
    if v is None or str(v).strip() == "":
        return None
    return v.strip()


def _normalize_base_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    u = url.strip()
    # Users sometimes paste '/v2' or trailing slashes; strip them.
    u = u.rstrip('/')
    # standard paper host
    if u.lower().endswith("/v2"):
        u = u[:-3]
    return u


class AlpacaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")
    # Defaults are benign; we will override with explicit envs below
    api_key_id: str = Field(default="")
    api_secret_key: str = Field(default="")
    base_url: str = Field(default="https://paper-api.alpaca.markets")
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


def _resolve_alpaca_from_env() -> Dict[str, Tuple[Optional[str], str]]:
    """
    Returns a mapping of field -> (value, source) without exposing secrets.
    Tries both ALPACA_* and APCA_* names; base URL from APCA_API_BASE_URL or ALPACA_API_BASE_URL.
    """

    key_env = _getenv("ALPACA_API_KEY_ID")
    fallback_key_env = _getenv("APCA_API_KEY_ID")
    key = key_env or fallback_key_env
    key_src = (
        "ALPACA_API_KEY_ID"
        if key_env
        else ("APCA_API_KEY_ID" if fallback_key_env else "-")
    )

    sec_env = _getenv("ALPACA_API_SECRET_KEY")
    fallback_sec_env = _getenv("APCA_API_SECRET_KEY")
    sec = sec_env or fallback_sec_env
    sec_src = (
        "ALPACA_API_SECRET_KEY"
        if sec_env
        else ("APCA_API_SECRET_KEY" if fallback_sec_env else "-")
    )

    url_env = _getenv("APCA_API_BASE_URL")
    fallback_url_env = _getenv("ALPACA_API_BASE_URL")
    url = _normalize_base_url(url_env or fallback_url_env)
    url_src = (
        "APCA_API_BASE_URL"
        if url_env
        else ("ALPACA_API_BASE_URL" if fallback_url_env else "-")
    )

    return {
        "api_key_id": (key, key_src),
        "api_secret_key": (sec, sec_src),
        "base_url": (url, url_src),
    }


def _effective_alpaca_settings() -> AlpacaSettings:
    """
    Merge dotenv/pydantic defaults with explicit env resolution; normalize base_url.
    """

    base = AlpacaSettings()  # loads from .env/etc
    env = _resolve_alpaca_from_env()
    key = env["api_key_id"][0] or base.api_key_id or ""
    sec = env["api_secret_key"][0] or base.api_secret_key or ""
    url = env["base_url"][0] or base.base_url or "https://paper-api.alpaca.markets"
    url = _normalize_base_url(url) or "https://paper-api.alpaca.markets"

    eff = AlpacaSettings(
        api_key_id=key,
        api_secret_key=sec,
        base_url=url,
        paper=("paper" in url.lower()),
        request_timeout_s=base.request_timeout_s,
        max_retries=base.max_retries,
        retry_backoff_s=base.retry_backoff_s,
    )
    return eff


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
    """Instantiate Alpaca configuration settings from the environment."""

    return _effective_alpaca_settings()


def get_order_defaults() -> OrderDefaults:
    """Instantiate order defaults from the environment."""

    return OrderDefaults()


def alpaca_config_ok() -> bool:
    s = get_alpaca_settings()
    return bool(s.api_key_id and s.api_secret_key and s.base_url)


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


def debug_alpaca_snapshot() -> Dict[str, Any]:
    base = AlpacaSettings()
    env = _resolve_alpaca_from_env()
    eff = _effective_alpaca_settings()
    return {
        "configured": alpaca_config_ok(),
        "base_url": eff.base_url,
        "paper": eff.paper,
        "key_tail": masked_tail(eff.api_key_id),
        "sources": {
            "api_key_id": env["api_key_id"][1] if env["api_key_id"][0] else ("BaseSettings" if base.api_key_id else "-"),
            "api_secret_key": env["api_secret_key"][1] if env["api_secret_key"][0] else ("BaseSettings" if base.api_secret_key else "-"),
            "base_url": env["base_url"][1] if env["base_url"][0] else ("BaseSettings" if base.base_url else "-"),
        },
    }
