from __future__ import annotations

import logging
from typing import Any

from app.execution.alpaca_adapter import AlpacaAdapter
from app.execution.adapters import MockBrokerAdapter
from core.runtime_flags import RuntimeFlags, require_alpaca_keys

log = logging.getLogger(__name__)


def make_broker_adapter(flags: RuntimeFlags) -> Any:
    """Return the appropriate broker adapter based on runtime flags."""

    if flags.mock_mode:
        log.info("broker=mock paper=True dry_run=%s", flags.dry_run)
        return MockBrokerAdapter()

    require_alpaca_keys()
    base_url = flags.alpaca_base_url
    paper = "paper-api.alpaca.markets" in base_url.lower()
    adapter = AlpacaAdapter(
        base_url=base_url,
        key_id=flags.alpaca_key,
        secret_key=flags.alpaca_secret,
    )
    setattr(adapter, "paper", paper)
    redacted = (flags.alpaca_key[-4:] if flags.alpaca_key else "none")
    log.info("broker=alpaca paper=%s key=***%s", paper, redacted)
    return adapter


__all__ = ["make_broker_adapter"]
