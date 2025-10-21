from __future__ import annotations

import os
from collections import deque
from pathlib import Path

from typing import Dict, List

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()

DEFAULT_LOG = os.getenv("APP_LOG_FILE", "logs/app.log")


def _tail(path: Path, n: int) -> list[str]:
    if not path.exists():
        return []
    dq: deque[str] = deque(maxlen=n)
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            dq.append(line.rstrip("\n"))
    return list(dq)


@router.get("/tail")
def logs_tail(lines: int = Query(200, ge=1, le=5000), file: str | None = None):
    """Return the last N lines of the primary log (or a specified file)."""

    try:
        path = Path(file) if file else Path(DEFAULT_LOG)
        return {"file": str(path), "lines": _tail(path, lines)}
    except Exception as exc:  # pragma: no cover - defensive guard
        raise HTTPException(500, f"logs_tail: {exc}") from exc


@router.get("/recent")
def recent_logs(limit: int = Query(200, ge=1, le=2000)) -> Dict[str, List[str]]:
    """Return the most recent log lines with a sensible default limit."""

    try:
        path = Path(DEFAULT_LOG)
        lines = _tail(path, limit)
        return {"lines": lines}
    except Exception:
        return {"lines": []}
