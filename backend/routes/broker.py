from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from backend.services import reconcile
from core.broker_config import is_mock

router = APIRouter(prefix="/broker", tags=["broker"])


@router.get("/account")
def account() -> Dict[str, Any]:
    if is_mock():
        return {
            "mock_mode": True,
            "equity": 0.0,
            "cash": 0.0,
            "buying_power": 0.0,
            "portfolio_value": 0.0,
        }
    try:
        payload = reconcile.pull_account()
    except Exception as exc:  # pragma: no cover - network path
        raise HTTPException(502, f"Alpaca account fetch failed: {exc}") from exc
    payload.setdefault("mock_mode", False)
    return payload


@router.get("/positions")
def positions() -> List[Dict[str, Any]]:
    if is_mock():
        return []
    try:
        return reconcile.pull_positions()
    except Exception as exc:  # pragma: no cover - network path
        raise HTTPException(502, f"Alpaca positions fetch failed: {exc}") from exc


@router.get("/orders")
def orders(limit: int = 50) -> List[Dict[str, Any]]:
    if is_mock():
        return []
    try:
        orders = reconcile.pull_orders()
    except Exception as exc:  # pragma: no cover - network path
        raise HTTPException(502, f"Alpaca orders fetch failed: {exc}") from exc
    return orders[:limit]
