"""Runtime settings helpers for broker routing and runtime profile."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from pydantic import BaseModel, Field

from core.runtime_flags import RuntimeFlags, get_runtime_flags


class AlpacaSettings(BaseModel):
    """Settings describing how to reach the Alpaca REST API."""

    base_url: str = Field(default="https://paper-api.alpaca.markets")
    key_id: Optional[str] = Field(default=None)
    secret_key: Optional[str] = Field(default=None)
    use_paper: bool = Field(default=True)

    @classmethod
    def from_env(cls, *, flags: RuntimeFlags | None = None) -> "AlpacaSettings":
        flags = flags or get_runtime_flags()
        base_url = flags.alpaca_base_url
        key_id = flags.alpaca_key or (
            os.getenv("ALPACA_KEY_ID")
            or os.getenv("ALPACA_API_KEY_ID")
            or os.getenv("APCA_API_KEY_ID")
        )
        secret_key = flags.alpaca_secret or (
            os.getenv("ALPACA_SECRET_KEY")
            or os.getenv("ALPACA_API_SECRET_KEY")
            or os.getenv("APCA_API_SECRET_KEY")
        )
        use_paper_flag = flags.paper_trading
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
    broker_mode: str = Field(default="paper")

    @classmethod
    def from_env(
        cls, *, alpaca: AlpacaSettings, flags: RuntimeFlags | None = None
    ) -> "RuntimeProfile":
        flags = flags or get_runtime_flags()
        profile = "live" if not flags.paper_trading and not flags.mock_mode else "paper"
        broker = flags.broker
        dry_run = flags.dry_run

        if flags.mock_mode:
            dry_run = True
        elif broker == "alpaca" and alpaca.key_id and alpaca.secret_key:
            dry_run = False

        return cls(
            profile=profile,
            broker=broker,
            dry_run=dry_run,
            broker_mode="mock" if flags.mock_mode else ("paper" if flags.paper_trading else "live"),
        )


class Settings(BaseModel):
    """Aggregate settings used by the backend and routers."""

    alpaca: AlpacaSettings
    runtime: RuntimeProfile
    api_base: str
    api_port: int
    ui_port: int

    @classmethod
    def from_env(cls) -> "Settings":
        flags = get_runtime_flags()
        alpaca = AlpacaSettings.from_env(flags=flags)
        runtime = RuntimeProfile.from_env(alpaca=alpaca, flags=flags)
        return cls(
            alpaca=alpaca,
            runtime=runtime,
            api_base=flags.api_base_url,
            api_port=flags.api_port,
            ui_port=flags.ui_port,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance loaded from environment variables."""

    return Settings.from_env()


__all__ = ["AlpacaSettings", "RuntimeProfile", "Settings", "get_settings"]
