"""Debug/diagnostic endpoints for the backend."""

from __future__ import annotations

from collections import deque
from pathlib import Path
from time import perf_counter
from typing import Any, Dict

import httpx
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


@router.get("/routes")
async def debug_routes() -> Dict[str, Dict[str, Any]]:
    """Probe key routes and return their status without propagating failures."""

    base = "http://127.0.0.1:8000"
    targets = [
        "/health",
        "/orchestrator/status",
        "/stream/status",
        "/broker/account",
        "/broker/orders",
        "/broker/positions",
        "/metrics/summary",
        "/features/indicators/AAPL",
    ]

    results: Dict[str, Dict[str, Any]] = {}
    async with httpx.AsyncClient(timeout=3.0) as client:
        for path in targets:
            start = perf_counter()
            try:
                response = await client.get(f"{base}{path}")
                ok = 200 <= response.status_code < 300
                sample: Any = None
                if ok:
                    try:
                        sample = response.json()
                    except Exception:  # pragma: no cover - sample best effort
                        sample = None
                results[path] = {
                    "ok": ok,
                    "status": response.status_code,
                    "elapsed_ms": int((perf_counter() - start) * 1000),
                    "sample": sample,
                }
            except Exception as exc:  # noqa: BLE001 - network failures reported in payload
                results[path] = {
                    "ok": False,
                    "status": None,
                    "elapsed_ms": int((perf_counter() - start) * 1000),
                    "error": repr(exc),
                }

    return results


__all__ = ["router"]
