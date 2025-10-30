from __future__ import annotations

import os
import threading
from typing import Optional

from .alpaca_adapter import AlpacaBrokerAdapter

__all__ = ["get_broker"]

_LOCK = threading.Lock()
_INSTANCE: Optional[AlpacaBrokerAdapter] = None
_SIGNATURE: Optional[tuple[str, str, bool]] = None


def _signature_from_env() -> tuple[str, str, bool]:
    key = os.getenv("ALPACA_KEY_ID") or os.getenv("APCA_API_KEY_ID") or ""
    secret = os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY") or ""
    profile = (os.getenv("PROFILE") or os.getenv("BROKER_MODE") or "paper").strip().lower()
    paper = profile != "live"
    return key, secret, paper


def get_broker() -> AlpacaBrokerAdapter:
    """Return a cached Alpaca broker adapter configured from environment variables."""

    global _INSTANCE, _SIGNATURE
    key, secret, paper = _signature_from_env()
    if not key or not secret:
        raise RuntimeError("Alpaca credentials are not configured")

    with _LOCK:
        signature = (key, secret, paper)
        if _INSTANCE is None or signature != _SIGNATURE:
            _INSTANCE = AlpacaBrokerAdapter(key, secret, paper=paper)
            _SIGNATURE = signature
        return _INSTANCE
