"""Structured logging helpers for runtime services."""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from typing import Any, Dict, Optional

_TRACE_KEY = "trace_id"


class JsonFormatter(logging.Formatter):
    """Render log records as JSON with optional trace metadata."""

    def format(self, record: logging.LogRecord) -> str:  # pragma: no cover - trivial
        base: Dict[str, Any] = {
            "ts": time.time(),
            "level": record.levelname,
            "msg": record.getMessage(),
            "logger": record.name,
        }
        trace = getattr(record, _TRACE_KEY, None)
        if trace:
            base[_TRACE_KEY] = trace
        extra = getattr(record, "extra", None)
        if isinstance(extra, dict):
            if _TRACE_KEY in extra and not trace:
                base[_TRACE_KEY] = extra[_TRACE_KEY]
            base.update({k: v for k, v in extra.items() if k != _TRACE_KEY})
        if record.exc_info:
            base["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(base, ensure_ascii=False)


def setup_logging() -> None:
    """Install a JSON formatter on the root logger using LOG_LEVEL."""

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(handler)


def with_trace(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Attach a fresh trace identifier to structured log metadata."""

    payload: Dict[str, Any] = {_TRACE_KEY: str(uuid.uuid4())}
    if extra:
        payload.update(extra)
    return payload
