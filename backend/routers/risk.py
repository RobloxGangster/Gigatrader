"""Risk configuration endpoints."""

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from .deps import get_risk_manager

router = APIRouter()


class RiskPatch(BaseModel):
    daily_loss_limit: Optional[float] = None
    max_positions: Optional[int] = None
    per_symbol_notional: Optional[float] = None
    portfolio_notional: Optional[float] = None
    bracket_enabled: Optional[bool] = None
    cooldown_sec: Optional[int] = None

    model_config = ConfigDict(extra="allow")


@router.get("/config")
def risk_config() -> Any:
    rm = get_risk_manager()
    try:
        return rm.snapshot()
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=500, detail=f"risk_config: {exc}") from exc


@router.post("/config")
def risk_config_update(patch: RiskPatch) -> Any:
    rm = get_risk_manager()
    try:
        payload = {k: v for k, v in patch.model_dump().items() if v is not None}
        return rm.apply_patch(payload)
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=400, detail=f"risk_config_update: {exc}") from exc


@router.post("/killswitch/engage")
def kill_switch_on() -> dict:
    rm = get_risk_manager()
    try:
        rm.engage_kill_switch()
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=500, detail=f"killswitch_engage: {exc}") from exc


@router.post("/killswitch/reset")
def kill_switch_off() -> dict:
    rm = get_risk_manager()
    try:
        rm.reset_kill_switch()
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=500, detail=f"killswitch_reset: {exc}") from exc
