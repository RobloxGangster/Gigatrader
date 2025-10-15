"""Extended telemetry metrics endpoints."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from core.kill_switch import KillSwitch
from services.safety import breakers
from services.telemetry import metrics

router = APIRouter(prefix="/metrics", tags=["metrics"])


_kill_switch = KillSwitch()


@router.get("/extended")
def metrics_extended() -> Dict[str, Any]:
    """Return aggregated telemetry suitable for dashboards."""

    snapshot = metrics.snapshot()
    snapshot["safety"] = breakers.breaker_state()
    snapshot["kill_switch"] = {"engaged": _kill_switch.engaged_sync()}
    return snapshot
