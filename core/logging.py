"""Structured logging utilities."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict

import orjson

DEFAULT_LOG_PATH = Path("logs/platform.log")
DEFAULT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


class JsonFormatter(logging.Formatter):
    """Render log records as JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "level": record.levelname,
            "message": record.getMessage(),
            "name": record.name,
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key.startswith("_extra_"):
                payload[key[7:]] = value
        return orjson.dumps(payload).decode()


def configure_logging(log_path: Path = DEFAULT_LOG_PATH) -> None:
    """Configure global logging handlers."""

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(log_path, maxBytes=5_000_000, backupCount=3)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)


configure_logging()
