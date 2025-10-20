"""Metrics endpoints surfaced in the Control Center."""

from fastapi import APIRouter, HTTPException

from .deps import get_metrics

router = APIRouter()


@router.get("/pnl/summary")
def pnl_summary() -> dict:
    metrics = get_metrics()
    try:
        return metrics.pnl_summary()
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=500, detail=f"pnl_summary: {exc}") from exc


@router.get("/telemetry/exposure")
def exposure() -> dict:
    metrics = get_metrics()
    try:
        return metrics.exposure()
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=500, detail=f"exposure: {exc}") from exc
