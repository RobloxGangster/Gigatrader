"""PnL summary endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .deps import get_metrics

router = APIRouter()


@router.get("/summary")
def pnl_summary() -> dict:
    metrics = get_metrics()
    try:
        return metrics.pnl_summary()
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=500, detail=f"pnl_summary: {exc}") from exc
