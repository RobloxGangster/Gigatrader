from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/diagnostics/run")
def diagnostics_run():
    """Lightweight self-check endpoint."""

    try:
        started_at = time.time()
        return {"ok": True, "started_at": started_at, "message": "Diagnostics complete"}
    except Exception as exc:  # pragma: no cover - defensive guard
        raise HTTPException(500, f"diagnostics_run: {exc}") from exc
