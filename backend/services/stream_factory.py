from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from app.market.stream_manager import StreamManager
from app.streams.factory import MockStream
from core.broker_config import AlpacaConfig
from core.runtime_flags import RuntimeFlags, require_alpaca_keys

log = logging.getLogger(__name__)


@dataclass
class StreamService:
    """Lightweight wrapper exposing a consistent stream interface."""

    client: Any
    source: str
    last_error: str | None = None

    def status(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"source": self.source}
        try:
            status = self.client.status() if hasattr(self.client, "status") else {}
        except Exception as exc:  # pragma: no cover - defensive guard
            self.last_error = str(exc)
            status = {"state": "offline"}
        if isinstance(status, dict):
            payload.update(status)
            running = status.get("running")
            if running is None:
                state = str(status.get("state") or status.get("status") or "").lower()
                running = state in {"online", "running", "connected"}
            if self.source == "mock" and not running:
                running = True
            payload["running"] = bool(running)
        if self.last_error:
            payload["last_error"] = self.last_error
        return payload

    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        if not hasattr(self.client, "start"):
            return
        try:
            self.client.start(loop)
            self.last_error = None
        except Exception as exc:  # pragma: no cover - surface via status
            self.last_error = str(exc)
            log.error("stream_start_failed source=%s error=%s", self.source, exc)
            raise

    def stop(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        if not hasattr(self.client, "stop"):
            return
        try:
            self.client.stop(loop)
        except Exception as exc:  # pragma: no cover - surface via status
            self.last_error = str(exc)
            log.error("stream_stop_failed source=%s error=%s", self.source, exc)
            raise


def _build_alpaca_config(flags: RuntimeFlags) -> AlpacaConfig:
    return AlpacaConfig(
        base_url=flags.alpaca_base_url,
        key_id=flags.alpaca_key or "",
        secret_key=flags.alpaca_secret or "",
    )


def make_stream_service(flags: RuntimeFlags) -> StreamService:
    if flags.mock_mode:
        return StreamService(client=MockStream(), source="mock")

    require_alpaca_keys()
    cfg = _build_alpaca_config(flags)
    manager = StreamManager(cfg)
    return StreamService(client=manager, source="alpaca")
 
 
 __all__ = ["StreamService", "make_stream_service"]
