"""Reconciliation endpoints for syncing state from Alpaca."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.execution.alpaca_adapter import AlpacaAdapter

from .broker import alpaca

router = APIRouter(tags=["reconcile"])


@router.post("/reconcile/sync")
def reconcile_now(adapter: AlpacaAdapter = Depends(alpaca)) -> dict:
    orders = adapter.list_orders(status="all", limit=200)
    positions = adapter.list_positions()
    return {"orders": len(orders), "positions": len(positions)}
