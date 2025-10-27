"""Reconciliation endpoints for syncing broker state."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from backend.routers.deps import BrokerService, get_broker, get_broker_adapter

router = APIRouter(prefix="/reconcile", tags=["reconcile"])


@router.post("/cancel_all")
def cancel_all(
    broker: BrokerService = Depends(get_broker),
    _adapter: Any = Depends(get_broker_adapter),
) -> dict[str, str]:
    try:
        broker.cancel_all_orders()
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001 - surface broker failures
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/sync")
def sync(
    broker: BrokerService = Depends(get_broker),
    _adapter: Any = Depends(get_broker_adapter),
):
    """Trigger broker reconciliation and return the adapter response."""

    try:
        if hasattr(broker, "reconcile_state"):
            return broker.reconcile_state()
        if hasattr(broker, "sync"):
            return broker.sync()
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001 - propagate failure with context
        raise HTTPException(status_code=500, detail=str(exc)) from exc


__all__ = ["router"]

