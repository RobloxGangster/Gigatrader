"""Debug/diagnostic endpoints for the backend."""

from __future__ import annotations

from collections import deque
from pathlib import Path

from fastapi import APIRouter, Query

router = APIRouter()

_EXECUTION_LOG_PATH = Path("logs/execution_debug.log")


def _tail_file(path: Path, limit: int) -> list[str]:
    if limit <= 0:
        return []
    if not path.exists() or not path.is_file():
        return []
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            return [line.rstrip("\n") for line in deque(handle, maxlen=limit)]
    except Exception:
        return []


@router.get("/execution_tail")
async def execution_tail(limit: int = Query(50, ge=1, le=500)) -> dict:
    """Return the tail of the execution log without failing."""

    lines = _tail_file(_EXECUTION_LOG_PATH, limit)
    return {"path": str(_EXECUTION_LOG_PATH), "lines": lines}


__all__ = ["router"]
