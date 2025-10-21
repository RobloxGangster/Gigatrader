"""Orchestrator endpoints for the Control Center."""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from .deps import get_orchestrator

router = APIRouter()


class OrchestratorStartPayload(BaseModel):
    preset: Optional[str] = None
    mode: Optional[str] = None

    model_config = ConfigDict(extra="allow")


@router.get("/status")
def orchestrator_status() -> dict:
    orch = get_orchestrator()
    try:
        return orch.status()
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=500, detail=f"orchestrator_status: {exc}") from exc


@router.post("/start")
def orchestrator_start(payload: OrchestratorStartPayload | None = None) -> dict:
    orch = get_orchestrator()
    try:
        preset = payload.preset if payload else None
        mode = (payload.mode or "paper") if payload else "paper"
        result = orch.start_sync(mode=mode, preset=preset)
        return {"ok": True, **result}
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=500, detail=f"orchestrator_start: {exc}") from exc


@router.post("/stop")
def orchestrator_stop() -> dict:
    orch = get_orchestrator()
    try:
        return orch.stop_sync()
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=500, detail=f"orchestrator_stop: {exc}") from exc
