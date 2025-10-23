from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


def _parse_bool(val: Optional[str], default: bool = False) -> bool:
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "on", "y"}


@dataclass
class StreamService:
    """
    Tiny facade describing the active market data stream source and health.
    This is intentionally minimal because the UI only queries /stream/status.
    """
    source: str  # "alpaca" | "mock"
    healthy: bool = True
    last_error: Optional[str] = None

    async def status(self) -> Dict[str, Any]:
        """
        Shape returned by the /stream/status endpoint.
        """
        return {
            "source": self.source,
            "healthy": bool(self.healthy),
            "error": self.last_error,
        }


def _alpaca_env_health() -> tuple[bool, Optional[str]]:
    """
    Validate presence of required Alpaca environment variables.
    Returns (healthy, error_message_if_any).
    """
    key = os.getenv("ALPACA_KEY_ID")
    secret = os.getenv("ALPACA_SECRET_KEY")
    base_url = os.getenv("ALPACA_BASE_URL")
    if not key or not secret or not base_url:
        msg = (
            "Missing Alpaca credentials: require ALPACA_KEY_ID, "
            "ALPACA_SECRET_KEY and ALPACA_BASE_URL."
        )
        return False, msg
    return True, None


def make_stream_service(flags: Any | None = None) -> StreamService:
    """
    Build a StreamService based on environment/runtime flags.
    - If MOCK_MODE=true -> mock source.
    - Otherwise -> alpaca; mark unhealthy with a precise error if creds missing.
    The optional `flags` arg is accepted for compatibility but not required.
    """
    mock_mode = _parse_bool(os.getenv("MOCK_MODE"), default=False)

    if mock_mode:
        log.info("Stream source selected: mock (MOCK_MODE=true)")
        return StreamService(source="mock", healthy=True)

    healthy, err = _alpaca_env_health()
    if not healthy:
        log.error("Stream source selected: alpaca, but unhealthy: %s", err)
        return StreamService(source="alpaca", healthy=False, last_error=err)

    log.info("Stream source selected: alpaca")
    return StreamService(source="alpaca", healthy=True)


__all__ = ["StreamService", "make_stream_service"]

