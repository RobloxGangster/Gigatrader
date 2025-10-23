"""Reconciliation endpoints for syncing state from Alpaca."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.execution.alpaca_adapter import AlpacaAdapter

# NOTE:
# Do not import symbols from broker router here.  Importing a concrete
# adapter (e.g. "alpaca") at import time creates circular deps and breaks
# uvicorn startup.  All broker access is resolved via deps/get_broker.
from backend.routers.deps import BrokerService, get_broker

router = APIRouter(tags=["reconcile"])


@router.post("/reconcile/sync")
def reconcile_now(service: BrokerService = Depends(get_broker)) -> dict:
    adapter: AlpacaAdapter = service.adapter
    orders = service.get_orders(status="all", limit=200)
    positions = service.get_positions()
    return {"orders": len(orders), "positions": len(positions)}
