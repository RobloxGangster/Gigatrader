from __future__ import annotations

from typing import Any

from backend.brokers import AlpacaBrokerAdapter, MockBrokerAdapter
from core.runtime_flags import RuntimeFlags, runtime_flags_from_env


def make_broker_adapter(flags: RuntimeFlags | None = None) -> Any:
    """Return the appropriate broker adapter based on runtime flags."""

    cfg = flags or runtime_flags_from_env()
    broker = (cfg.broker or "alpaca").lower()

    if broker == "alpaca" and not cfg.mock_mode:
        adapter = AlpacaBrokerAdapter.from_runtime_flags(cfg)
        return adapter

    if cfg.mock_mode or broker == "mock":
        adapter = MockBrokerAdapter()
        setattr(adapter, "dry_run", bool(cfg.dry_run))
        setattr(adapter, "profile", getattr(cfg, "profile", "mock"))
        return adapter

    raise ValueError(
        f"Unsupported broker config: broker={cfg.broker}, mock_mode={cfg.mock_mode}"
    )


__all__ = ["make_broker_adapter"]
