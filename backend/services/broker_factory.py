from __future__ import annotations

import logging
from typing import Any

from app.execution.alpaca_adapter import AlpacaAdapter
from app.execution.adapters import MockBrokerAdapter
from core.runtime_flags import RuntimeFlags, require_alpaca_keys

log = logging.getLogger(__name__)


def make_broker_adapter(flags: RuntimeFlags) -> Any:
    """Return the appropriate broker adapter based on runtime flags."""

    broker = (flags.broker or "alpaca").lower()

    if broker == "alpaca" and not flags.mock_mode:
        require_alpaca_keys()
        base_url = flags.alpaca_base_url
        paper = bool(flags.paper_trading)
        adapter = AlpacaAdapter(
            base_url=base_url,
            key_id=flags.alpaca_key,
            secret_key=flags.alpaca_secret,
        )
        profile = "paper" if paper else "live"
        setattr(adapter, "paper", paper)
        setattr(adapter, "profile", profile)
        setattr(adapter, "dry_run", bool(flags.dry_run))
        setattr(adapter, "name", "alpaca")
        redacted = (flags.alpaca_key[-4:] if flags.alpaca_key else "none")
        log.info(
            "broker=alpaca profile=%s dry_run=%s key=***%s",
            profile,
            flags.dry_run,
            redacted,
        )
        return adapter

    if flags.mock_mode or broker == "mock":
        log.info("broker=mock dry_run=%s", flags.dry_run)
        adapter = MockBrokerAdapter()
        setattr(adapter, "name", "mock")
        setattr(adapter, "dry_run", bool(flags.dry_run))
        setattr(adapter, "profile", "mock")
        return adapter

    raise ValueError(f"Unsupported broker: {flags.broker}")


__all__ = ["make_broker_adapter"]
