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


class OrchestratorStatus(BaseModel):
    running: bool
    last_start: str | None = None
    last_error: str | None = None

    model_config = ConfigDict(extra="allow")


def _build_status(snapshot: dict) -> OrchestratorStatus:
    payload = dict(snapshot)
    payload.setdefault("running", bool(snapshot.get("running")))
    payload.setdefault("last_start", snapshot.get("last_start"))
    payload.setdefault("last_error", snapshot.get("last_error"))
    return OrchestratorStatus(**payload)


@router.get("/status", response_model=OrchestratorStatus)
def orchestrator_status() -> OrchestratorStatus:
    orch = get_orchestrator()
    try:
        snapshot = orch.status()
        return _build_status(snapshot)
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=500, detail=f"orchestrator_status: {exc}") from exc


@router.post("/start", response_model=OrchestratorStatus)
def orchestrator_start(payload: OrchestratorStartPayload | None = None) -> OrchestratorStatus:
    orch = get_orchestrator()
    try:
        preset = payload.preset if payload else None
        mode = (payload.mode or "paper") if payload else "paper"
        result = orch.start_sync(mode=mode, preset=preset)
        snapshot = orch.status()
        payload = {**snapshot, **result}
        return _build_status(payload)
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=500, detail=f"orchestrator_start: {exc}") from exc


@router.post("/stop", response_model=OrchestratorStatus)
def orchestrator_stop() -> OrchestratorStatus:
    orch = get_orchestrator()
    try:
        result = orch.stop_sync()
        snapshot = orch.status()
        payload = {**snapshot, **result}
        return _build_status(payload)
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=500, detail=f"orchestrator_stop: {exc}") from exc
