from __future__ import annotations

import time
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query

from ..services.reconcile import (
    is_mock,
    pull_account,
    pull_all_if_live,
    pull_orders,
    pull_positions,
)

router = APIRouter(tags=["alpaca-live"])


@router.get("/alpaca/account")
def account() -> Dict[str, Any]:
    if is_mock():
        # allow UI to render gracefully; empty payload
        return {"mock_mode": True}
    try:
        acc = pull_account()
    except Exception as e:  # pragma: no cover - network errors
        raise HTTPException(502, f"Alpaca account fetch failed: {e}") from e
    # Normalize common names
    pv = acc.get("portfolio_value") or acc.get("equity")
    return {
        "mock_mode": False,
        "equity": acc.get("equity"),
        "cash": acc.get("cash"),
        "buying_power": acc.get("buying_power"),
        "portfolio_value": pv,
        "_raw": acc,
    }


@router.post("/orders/sync")
def orders_sync() -> Dict[str, Any]:
    if is_mock():
        return {"mock_mode": True, "synced": False, "reason": "MOCK_MODE"}
    data = pull_all_if_live()
    # If you have an OMS DB, persist/merge here; for now return pass-through
    return {"mock_mode": False, "synced": True, "ts": int(time.time()), **data}


@router.get("/positions")
def positions(live: bool = Query(False)) -> List[Dict[str, Any]]:  # noqa: ARG001
    if is_mock():
        return []
    try:
        return pull_positions() if live else pull_positions()
    except Exception as e:  # pragma: no cover - network errors
        raise HTTPException(502, f"Alpaca positions failed: {e}") from e


@router.get("/orders")
def orders(live: bool = Query(False)) -> List[Dict[str, Any]]:  # noqa: ARG001
    if is_mock():
        return []
    try:
        return pull_orders() if live else pull_orders()
    except Exception as e:  # pragma: no cover - network errors
        raise HTTPException(502, f"Alpaca orders failed: {e}") from e
