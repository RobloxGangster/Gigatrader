"""General utilities."""
from __future__ import annotations

import hashlib
import os
from typing import Any


def idempotency_key(payload: Any) -> str:
    """Generate a deterministic idempotency key from ``payload``."""

    data = repr(sorted(payload.items()) if isinstance(payload, dict) else payload).encode()
    return hashlib.sha256(data).hexdigest()


def ensure_paper_mode(default: bool = True) -> str:
    """Return Alpaca environment name respecting paper-default guardrails."""

    live_flag = os.getenv("LIVE_TRADING", "false").lower() == "true"
    if default and not live_flag:
        return "paper"
    return "live"
