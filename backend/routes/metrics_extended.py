"""Extended telemetry metrics endpoints."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from services.telemetry import metrics

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/extended")
def metrics_extended() -> Dict[str, Any]:
    """Return aggregated telemetry suitable for dashboards."""

    snapshot = metrics.snapshot()
    return snapshot
