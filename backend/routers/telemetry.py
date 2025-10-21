"""Telemetry endpoints exposed to the Control Center."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .deps import get_metrics

router = APIRouter()


@router.get("/exposure")
def exposure() -> dict:
    metrics = get_metrics()
    try:
        return metrics.exposure()
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=500, detail=f"exposure: {exc}") from exc
