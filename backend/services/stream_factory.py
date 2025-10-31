from __future__ import annotations

import logging
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol

from core.runtime_flags import RuntimeFlags, get_runtime_flags


log = logging.getLogger(__name__)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class StreamService(Protocol):
    source: str
    running: bool
    last_error: Optional[str]

    @property
    def source_name(self) -> str: ...

    async def status(self) -> Dict[str, Any]: ...

    def start(self, loop: Any | None = None) -> None: ...

    def stop(self, loop: Any | None = None) -> None: ...


class BaseStreamService:
    def __init__(self, source: str) -> None:
        # The `source` string is surfaced directly to the UI badges and controls.
        # It must accurately reflect the market data feed that is currently in use
        # (e.g. "mock", "alpaca", "alpaca/paper"). Do not lie here — other
        # services rely on this to decide whether the system is operating against
        # live infrastructure or simulated data.
        self.source = source
        self.running: bool = False
        self.last_error: Optional[str] = None
        self._last_heartbeat: Optional[str] = None
        self._rpm: float = 0.0
        self._backoff_events: int = 0
        self._retries: int = 0
        self._max_rpm: float = 0.0
        self._window_seconds: float = 60.0
        self._history: List[Dict[str, Any]] = []

    @property
    def last_heartbeat(self) -> Optional[str]:
        return self._last_heartbeat

    def _mark_heartbeat(self) -> str:
        ts = _iso_now()
        self._last_heartbeat = ts
        return ts

    @property
    def source_name(self) -> str:
        return self.source

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
            "rpm": self._rpm,
            "backoff_events": self._backoff_events,
            "retries": self._retries,
            "max_rpm": self._max_rpm or self._rpm,
            "window_seconds": self._window_seconds,
        }
        if self.last_error:
            payload["last_error"] = self.last_error
        self._history.append(
            {
                "ts": heartbeat,
                "ok": payload["ok"],
                "running": self.running,
                "error": self.last_error,
            }
        )
        if len(self._history) > 100:
            del self._history[:-100]
        payload["history"] = list(self._history[-20:])
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
        normalized = (profile or "paper").strip().lower() or "paper"
        source = "alpaca/live" if normalized == "live" else "alpaca/paper"
        super().__init__(source)
        self.profile = normalized
        self.running = True
        self._mark_heartbeat()

    async def status(self) -> Dict[str, Any]:
        healthy, err = _alpaca_env_health()
        self.last_error = err
        payload = await super().status()
        payload["profile"] = self.profile
        payload["ok"] = healthy
        payload["status"] = "online" if healthy else "degraded"
        if err:
            payload["last_error"] = err
        return payload


def make_stream_service(flags: RuntimeFlags | None = None) -> StreamService:
    cfg = flags or get_runtime_flags()
    source = (cfg.market_data_source or "mock").lower()

    if cfg.mock_mode:
        log.info("Stream source selected: mock (mock_mode=true)")
        return MockStreamService()

    if source == "mock":
        raise RuntimeError(
            "Mock stream selected while MOCK_MODE=false; update MARKET_DATA_SOURCE or enable mock mode."
        )

    if source.startswith("alpaca"):
        healthy, err = _alpaca_env_health()
        profile = getattr(cfg, "profile", "paper")
        if not healthy:
            detail = err or "missing credentials"
            log.warning("Stream source alpaca unhealthy: %s", detail)
        log.info("Stream source selected: alpaca (profile=%s)", profile)
        return AlpacaStreamService(profile=profile)

    raise RuntimeError(f"Unsupported market_data_source: {cfg.market_data_source}")


__all__ = [
    "AlpacaStreamService",
    "MockStreamService",
    "StreamService",
    "make_stream_service",
]

