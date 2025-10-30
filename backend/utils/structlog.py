"""Structured logging helpers for Gigatrader."""

from __future__ import annotations

import json
import logging
import time
from typing import Any


_log = logging.getLogger("gigatrader")


def jlog(event: str, /, **kv: Any) -> None:
    """Emit a compact JSON debug log with a consistent schema."""

    payload: dict[str, Any] = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": event,
    }
    payload.update(kv)
    _log.debug(json.dumps(payload, separators=(",", ":"), default=str))


__all__ = ["jlog"]

