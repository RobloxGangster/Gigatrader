from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Protocol

from core.runtime_flags import RuntimeFlags, runtime_flags_from_env


log = logging.getLogger(__name__)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class StreamService(Protocol):
    source: str
    running: bool
    last_error: Optional[str]

    async def status(self) -> Dict[str, Any]: ...

    def start(self, loop: Any | None = None) -> None: ...

    def stop(self, loop: Any | None = None) -> None: ...


class BaseStreamService:
    def __init__(self, source: str) -> None:
        self.source = source
        self.running: bool = False
        self.last_error: Optional[str] = None
        self._last_heartbeat: Optional[str] = None

    @property
    def last_heartbeat(self) -> Optional[str]:
        return self._last_heartbeat

    def _mark_heartbeat(self) -> str:
        ts = _iso_now()
        self._last_heartbeat = ts
        return ts

    def start(self, loop: Any | None = None) -> None:
        self.running = True
        self._mark_heartbeat()

    def stop(self, loop: Any | None = None) -> None:
        self.running = False
        self._mark_heartbeat()

    async def status(self) -> Dict[str, Any]:
        heartbeat = self._mark_heartbeat()
        payload: Dict[str, Any] = {
            "source": self.source,
            "running": self.running,
            "last_heartbeat": heartbeat,
            "status": "online" if self.running and not self.last_error else "degraded",
            "ok": self.running and not self.last_error,
        }
        if self.last_error:
            payload["last_error"] = self.last_error
        return payload


class MockStreamService(BaseStreamService):
    def __init__(self) -> None:
        super().__init__("mock")
        self.start()

    async def status(self) -> Dict[str, Any]:
        return await super().status()


def _alpaca_env_health() -> tuple[bool, Optional[str]]:
    key = (os.getenv("ALPACA_KEY_ID") or os.getenv("ALPACA_API_KEY_ID") or "").strip()
    secret = (os.getenv("ALPACA_SECRET_KEY") or os.getenv("ALPACA_API_SECRET_KEY") or "").strip()
    base_url = (os.getenv("ALPACA_BASE_URL") or os.getenv("APCA_API_BASE_URL") or "").strip()
    if not key or not secret or not base_url:
        return False, "Missing Alpaca credentials"
    return True, None


class AlpacaStreamService(BaseStreamService):
    def __init__(self, *, profile: str = "paper") -> None:
        super().__init__("alpaca")
        self.profile = profile
        self.running = True
        self._mark_heartbeat()

    async def status(self) -> Dict[str, Any]:
        healthy, err = _alpaca_env_health()
        self.last_error = err
        heartbeat = self._mark_heartbeat()
        payload: Dict[str, Any] = {
            "source": self.source,
            "running": self.running,
            "profile": self.profile,
            "last_heartbeat": heartbeat,
            "ok": healthy,
            "status": "online" if healthy else "degraded",
        }
        if err:
            payload["last_error"] = err
        return payload


def make_stream_service(flags: RuntimeFlags | None = None) -> StreamService:
    cfg = flags or runtime_flags_from_env()
    source = (cfg.market_data_source or "mock").lower()

    if source == "mock":
        log.info("Stream source selected: mock")
        return MockStreamService()

    if source == "alpaca":
        log.info("Stream source selected: alpaca (profile=%s)", getattr(cfg, "profile", "paper"))
        return AlpacaStreamService(profile=getattr(cfg, "profile", "paper"))

    log.warning("Unknown market_data_source %s, defaulting to mock", source)
    return MockStreamService()


__all__ = [
    "AlpacaStreamService",
    "MockStreamService",
    "StreamService",
    "make_stream_service",
]

