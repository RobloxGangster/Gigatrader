from __future__ import annotations

import asyncio
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from core.runtime_flags import get_runtime_flags, require_alpaca_keys

from backend.services.orchestrator import (
    get_last_order_attempt,
    get_orchestrator_status,
)

from .deps import get_orchestrator

router = APIRouter()


class OrchestratorStartPayload(BaseModel):
    preset: Optional[str] = None
    mode: Optional[str] = None

    model_config = ConfigDict(extra="allow")


class OrchestratorStatus(BaseModel):
    state: Literal["running", "stopped"]
    running: bool
    last_error: str | None = None
    last_heartbeat: str | None = None
    uptime_secs: float = 0.0
    restart_count: int = 0

    model_config = ConfigDict(extra="allow")


def _build_status(snapshot: dict) -> OrchestratorStatus:
    payload = {
        "state": str(snapshot.get("state") or "stopped"),
        "running": bool(snapshot.get("running")),
        "last_error": snapshot.get("last_error"),
        "last_heartbeat": snapshot.get("last_heartbeat"),
        "uptime_secs": float(snapshot.get("uptime_secs") or 0.0),
        "restart_count": int(snapshot.get("restart_count") or 0),
    }
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
async def orchestrator_start(payload: OrchestratorStartPayload | None = None) -> OrchestratorStatus:
    orch = get_orchestrator()
    try:
        flags = get_runtime_flags()
        if not flags.mock_mode:
            try:
                require_alpaca_keys()
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        await orch.start()
        await asyncio.sleep(0)
        snapshot = orch.status()
        if payload and payload.preset:
            snapshot["preset"] = payload.preset
        return _build_status(snapshot)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=500, detail=f"orchestrator_start: {exc}") from exc


@router.post("/stop", response_model=OrchestratorStatus)
async def orchestrator_stop() -> OrchestratorStatus:
    orch = get_orchestrator()
    try:
        await orch.stop()
        snapshot = orch.status()
        return _build_status(snapshot)
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=500, detail=f"orchestrator_stop: {exc}") from exc


@router.get("/debug")
async def orchestrator_debug() -> dict:
    return {
        "status": get_orchestrator_status(),
        "last_order_attempt": get_last_order_attempt(),
    }
