from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from core.runtime_flags import get_runtime_flags, require_live_alpaca_or_fail
from backend.models.orchestrator import OrchestratorStatus
from backend.services.orchestrator import (
    get_last_order_attempt,
    get_orchestrator_status,
)
from backend.services.orchestrator_manager import orchestrator_manager
from backend.services.orchestrator_runner import run_trading_loop

from .deps import get_orchestrator


router = APIRouter()


class OrchestratorStartPayload(BaseModel):
    preset: Optional[str] = None
    mode: Optional[str] = None

    model_config = ConfigDict(extra="allow")


def _ensure_status(data: OrchestratorStatus | dict[str, Any]) -> OrchestratorStatus:
    if isinstance(data, OrchestratorStatus):
        return data
    return OrchestratorStatus(**data)


def _with_manager(
    status: OrchestratorStatus, manager_snapshot: dict[str, Any] | None, **extra: Any
) -> OrchestratorStatus:
    update: dict[str, Any] = {"manager": manager_snapshot}
    if manager_snapshot is not None and not status.thread_alive:
        update["thread_alive"] = bool(manager_snapshot.get("thread_alive"))
    if extra:
        update.update(extra)
    return status.model_copy(update=update)


@router.get("/status", response_model=OrchestratorStatus)
def orchestrator_status() -> OrchestratorStatus:
    orchestrator = get_orchestrator()
    try:
        status = _ensure_status(orchestrator.status())
        manager_snapshot = orchestrator_manager.get_status()
        return _with_manager(status, manager_snapshot)
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=500, detail=f"orchestrator_status: {exc}") from exc


@router.post("/start", response_model=OrchestratorStatus)
async def orchestrator_start(
    payload: OrchestratorStartPayload | None = None,
) -> OrchestratorStatus:
    try:
        flags = get_runtime_flags()
        if not flags.mock_mode:
            try:
                require_live_alpaca_or_fail()
            except RuntimeError as exc:
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
        status = _ensure_status(orchestrator.status())
        extra: dict[str, Any] = {}
        if payload and payload.preset:
            extra["preset"] = payload.preset
        return _with_manager(status, manager_snapshot, **extra)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=500, detail=f"orchestrator_start: {exc}") from exc


@router.post("/stop", response_model=OrchestratorStatus)
async def orchestrator_stop() -> OrchestratorStatus:
    try:
        manager_snapshot = orchestrator_manager.stop("api.stop")
        status = _ensure_status(get_orchestrator().status())
        return _with_manager(status, manager_snapshot)
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        status = _ensure_status(get_orchestrator().status())
        manager_snapshot = orchestrator_manager.get_status()
        return _with_manager(status, manager_snapshot, ok=False, error=f"orchestrator_stop: {exc}")


@router.post("/reset_kill_switch", response_model=OrchestratorStatus)
def orchestrator_reset_kill_switch() -> OrchestratorStatus:
    try:
        orchestrator = get_orchestrator()
        orchestrator.reset_kill_switch(requested_by="api.reset")
        status = _ensure_status(orchestrator.status())
        return _with_manager(status, orchestrator_manager.get_status())
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        status = _ensure_status(get_orchestrator().status())
        manager_snapshot = orchestrator_manager.get_status()
        return _with_manager(
            status,
            manager_snapshot,
            ok=False,
            error=f"orchestrator_reset_kill_switch: {exc}",
        )


@router.get("/debug")
async def orchestrator_debug() -> dict[str, Any]:
    status = get_orchestrator_status()
    return {
        "status": {
            **status.model_dump(),
            "manager": orchestrator_manager.get_status(),
        },
        "last_order_attempt": get_last_order_attempt(),
    }


__all__ = ["router", "orchestrator_status", "orchestrator_start"]

