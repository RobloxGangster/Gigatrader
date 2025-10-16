"""Pacing telemetry endpoint."""

from __future__ import annotations

from typing import Dict, Any

from fastapi import APIRouter

from backend.pacing import load_pacing_snapshot

router = APIRouter(tags=["pacing"])


@router.get("/pacing")
def pacing_snapshot() -> Dict[str, Any]:
    """Return pacing/rate-limit telemetry for the control center UI."""

    return load_pacing_snapshot()

