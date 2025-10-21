"""Runtime settings helpers for broker routing and runtime profile."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from pydantic import BaseModel, Field


class AlpacaSettings(BaseModel):
    """Settings describing how to reach the Alpaca REST API."""

    base_url: str = Field(default="https://paper-api.alpaca.markets")
    key_id: Optional[str] = Field(default=None)
    secret_key: Optional[str] = Field(default=None)
    use_paper: bool = Field(default=True)

    @classmethod
    def from_env(cls) -> "AlpacaSettings":
        base_url = (
            os.getenv("ALPACA_BASE_URL")
            or os.getenv("APCA_API_BASE_URL")
            or "https://paper-api.alpaca.markets"
        )
        base_url = base_url.rstrip("/") or "https://paper-api.alpaca.markets"
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
        use_paper = os.getenv("ALPACA_USE_PAPER") or (
            "paper" if "paper" in base_url.lower() else "false"
        )
        use_paper_flag = str(use_paper).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
            "paper",
        }
        return cls(
            base_url=base_url,
            key_id=key_id,
            secret_key=secret_key,
            use_paper=use_paper_flag,
        )


class RuntimeProfile(BaseModel):
    """Describes the runtime profile of the trading application."""

    profile: str = Field(default="paper")
    broker: str = Field(default="alpaca")
    dry_run: bool = Field(default=False)

    @classmethod
    def from_env(cls, *, alpaca: AlpacaSettings) -> "RuntimeProfile":
        profile = os.getenv("PROFILE", "paper").strip().lower() or "paper"
        broker = os.getenv("BROKER", "alpaca").strip().lower() or "alpaca"
        dry_run_value = os.getenv("DRY_RUN", "false")
        dry_run = str(dry_run_value).strip().lower() in {"1", "true", "yes", "on"}

        if profile in {"paper", "live"}:
            broker = "alpaca"
        if alpaca.key_id and alpaca.secret_key:
            broker = "alpaca"
            dry_run = False
        if profile not in {"paper", "live"}:
            profile = "paper"
        if broker != "alpaca" and profile in {"paper", "live"}:
            broker = "alpaca"
        return cls(profile=profile, broker=broker, dry_run=dry_run)


class Settings(BaseModel):
    """Aggregate settings used by the backend and routers."""

    alpaca: AlpacaSettings
    runtime: RuntimeProfile

    @classmethod
    def from_env(cls) -> "Settings":
        alpaca = AlpacaSettings.from_env()
        runtime = RuntimeProfile.from_env(alpaca=alpaca)
        return cls(alpaca=alpaca, runtime=runtime)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance loaded from environment variables."""

    return Settings.from_env()


__all__ = ["AlpacaSettings", "RuntimeProfile", "Settings", "get_settings"]
