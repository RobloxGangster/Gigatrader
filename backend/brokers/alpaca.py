from __future__ import annotations

import logging

from typing import Mapping

from app.execution.alpaca_adapter import AlpacaAdapter
from core.runtime_flags import RuntimeFlags, runtime_flags_from_env
from core.runtime_flags import require_alpaca_keys

logger = logging.getLogger(__name__)


class AlpacaBrokerAdapter(AlpacaAdapter):
    """Thin wrapper around :class:`~app.execution.alpaca_adapter.AlpacaAdapter`."""

    @classmethod
    def from_runtime_flags(cls, flags: RuntimeFlags) -> "AlpacaBrokerAdapter":
        require_alpaca_keys()
        adapter = cls(
            base_url=flags.alpaca_base_url,
            key_id=flags.alpaca_key,
            secret_key=flags.alpaca_secret,
        )
        profile = (flags.profile or "paper").lower()
        adapter.profile = profile
        adapter.dry_run = flags.dry_run
        adapter.paper = bool(flags.paper_trading and profile != "live")
        adapter.name = "alpaca"
        logger.info(
            "broker.adapter.alpaca",  # pragma: no cover - structured logging
            extra={
                "profile": profile,
                "dry_run": adapter.dry_run,
                "paper": adapter.paper,
            },
        )
        return adapter

    @classmethod
    def from_env(cls, *, profile: str, dry_run: bool) -> "AlpacaBrokerAdapter":
        flags = runtime_flags_from_env().copy(update={"profile": profile, "dry_run": dry_run})
        return cls.from_runtime_flags(flags)

    def place_order(self, payload: Mapping[str, object]):  # type: ignore[override]
        logger.info(
            "broker.order.submit",
            extra={
                "symbol": payload.get("symbol"),
                "side": payload.get("side"),
                "qty": payload.get("qty"),
                "dry_run": getattr(self, "dry_run", False),
                "profile": getattr(self, "profile", None),
            },
        )
        return super().place_order(payload)
