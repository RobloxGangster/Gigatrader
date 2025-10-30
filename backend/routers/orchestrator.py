from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from core.runtime_flags import get_runtime_flags, require_alpaca_keys

from backend.services.orchestrator import (
    get_last_order_attempt,
    get_orchestrator_status,
)
from backend.models.orchestrator import OrchestratorStatus as OrchestratorStatusModel, OrchState
from backend.services.orchestrator_manager import orchestrator_manager
from backend.services.orchestrator_runner import run_trading_loop

from .deps import get_orchestrator

router = APIRouter()


class OrchestratorStartPayload(BaseModel):
    preset: Optional[str] = None
    mode: Optional[str] = None

    model_config = ConfigDict(extra="allow")


class OrchestratorStatus(OrchestratorStatusModel):
    model_config = ConfigDict(extra="allow")


def _build_status(snapshot: dict) -> OrchestratorStatus:
    payload = dict(snapshot)
    raw_state = str(snapshot.get("state") or "stopped")
    allowed: set[str] = {"starting", "running", "stopping", "stopped"}
    coerced_state: OrchState
    if raw_state in allowed:
        coerced_state = raw_state  # type: ignore[assignment]
    else:
        coerced_state = "running" if bool(snapshot.get("running")) else "stopped"
    payload["state"] = coerced_state
    payload["running"] = bool(snapshot.get("running"))
    payload["last_error"] = snapshot.get("last_error")
    payload["thread_alive"] = bool(snapshot.get("thread_alive"))
    payload["last_heartbeat"] = snapshot.get("last_heartbeat")
    payload["uptime_secs"] = float(snapshot.get("uptime_secs") or 0.0)
    if "uptime" not in payload and snapshot.get("uptime_secs") is not None:
        payload["uptime"] = f"{float(snapshot.get('uptime_secs') or 0.0):.2f}s"
    payload["restart_count"] = int(snapshot.get("restart_count") or 0)
    manager_status = snapshot.get("manager")
    if manager_status is not None:
        thread_alive = bool(manager_status.get("thread_alive"))
        manager_state = str(
            manager_status.get("state")
            or ("running" if thread_alive else "stopped")
        )
        payload["manager"] = {
            **manager_status,
            "state": manager_state,
            "thread_alive": thread_alive,
        }
        payload.setdefault("thread_alive", thread_alive)
    return OrchestratorStatus(**payload)


@router.get("/status", response_model=OrchestratorStatus)
def orchestrator_status() -> OrchestratorStatus:
    orch = get_orchestrator()
    try:
        snapshot = orch.status()
        snapshot["manager"] = orchestrator_manager.get_status()
        return _build_status(snapshot)
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=500, detail=f"orchestrator_status: {exc}") from exc


@router.post("/start", response_model=OrchestratorStatus)
async def orchestrator_start(payload: OrchestratorStartPayload | None = None) -> OrchestratorStatus:
    try:
        flags = get_runtime_flags()
        if not flags.mock_mode:
            try:
                require_alpaca_keys()
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        orchestrator = get_orchestrator()
        arm_snapshot = orchestrator.safe_arm_trading(requested_by="api.start")
        if arm_snapshot.get("engaged"):
            reason = arm_snapshot.get("reason")
            reason_label = reason or "kill_switch_engaged"
            raise HTTPException(
                status_code=409,
                detail=f"kill switch engaged ({reason_label}); reset before starting",
            )
        manager_snapshot = orchestrator_manager.start(run_trading_loop)
        snapshot = orchestrator.status()
        snapshot["manager"] = manager_snapshot
        snapshot["kill_switch_engaged"] = bool(snapshot.get("kill_switch_engaged"))
        if payload and payload.preset:
            snapshot["preset"] = payload.preset
        return _build_status(snapshot)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=500, detail=f"orchestrator_start: {exc}") from exc


@router.post("/stop", response_model=OrchestratorStatus)
async def orchestrator_stop() -> OrchestratorStatus:
    try:
        manager_snapshot = orchestrator_manager.stop("api.stop")
        orchestrator = get_orchestrator()
        snapshot = orchestrator.status()
        snapshot["manager"] = manager_snapshot
        return _build_status(snapshot)
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        orchestrator = get_orchestrator()
        snapshot = orchestrator.status()
        snapshot["manager"] = orchestrator_manager.get_status()
        snapshot["ok"] = False
        snapshot["error"] = f"orchestrator_stop: {exc}"
        return _build_status(snapshot)


@router.post("/reset_kill_switch", response_model=OrchestratorStatus)
def orchestrator_reset_kill_switch() -> OrchestratorStatus:
    try:
        orchestrator = get_orchestrator()
        orchestrator.reset_kill_switch(requested_by="api.reset")
        snapshot = orchestrator.status()
        snapshot["manager"] = orchestrator_manager.get_status()
        return _build_status(snapshot)
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        orchestrator = get_orchestrator()
        snapshot = orchestrator.status()
        snapshot["manager"] = orchestrator_manager.get_status()
        snapshot["ok"] = False
        snapshot["error"] = f"orchestrator_reset_kill_switch: {exc}"
        return _build_status(snapshot)


@router.get("/debug")
async def orchestrator_debug() -> dict:
    return {
        "status": {
            **get_orchestrator_status(),
            "manager": orchestrator_manager.get_status(),
        },
        "last_order_attempt": get_last_order_attempt(),
    }
