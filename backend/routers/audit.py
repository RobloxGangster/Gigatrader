"""Audit log tail endpoint."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query

router = APIRouter(tags=["audit"])

LOG_PATH = Path("logs") / "audit.log"


@router.get("/audit/tail")
def tail(n: int = Query(200, ge=1, le=1000)) -> dict:
    if not LOG_PATH.exists():
        return {"lines": []}
    try:
        lines = LOG_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:  # noqa: BLE001 - defensive guard
        return {"lines": []}
    return {"lines": lines[-n:]}
