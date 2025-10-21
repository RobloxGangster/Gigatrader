"""Broker endpoints used by the Control Center UI."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query

from app.execution.alpaca_adapter import AlpacaOrderError, AlpacaUnauthorized

from .deps import get_broker

router = APIRouter()

_MOCK_ACCOUNT: Dict[str, float | str] = {
    "equity": 100_000.0,
    "cash": 75_000.0,
    "buying_power": 150_000.0,
    "portfolio_value": 100_000.0,
    "status": "ACTIVE",
}

_MOCK_POSITIONS: List[Dict[str, Any]] = [
    {
        "symbol": "AAPL",
        "qty": 10.0,
        "avg_entry_price": 175.0,
        "market_value": 1750.0,
        "unrealized_pl": 25.0,
        "unrealized_plpc": 0.0143,
    },
    {
        "symbol": "MSFT",
        "qty": 5.0,
        "avg_entry_price": 320.0,
        "market_value": 1600.0,
        "unrealized_pl": -40.0,
        "unrealized_plpc": -0.0247,
    },
]

_MOCK_ORDERS: List[Dict[str, Any]] = [
    {
        "id": "MOCK-1",
        "symbol": "AAPL",
        "side": "buy",
        "qty": 10.0,
        "status": "filled",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "filled_qty": 10.0,
        "avg_fill_price": 174.5,
    },
    {
        "id": "MOCK-2",
        "symbol": "MSFT",
        "side": "sell",
        "qty": 5.0,
        "status": "accepted",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "filled_qty": 0.0,
        "avg_fill_price": 0.0,
    },
]


def _alpaca_env_present() -> bool:
    required = ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "APCA_API_BASE_URL")
    return all(os.getenv(name) for name in required)


@router.get("/broker/account")
def broker_account() -> dict:
    if not _alpaca_env_present():
        return _MOCK_ACCOUNT.copy()
    broker = get_broker()
    try:
        return broker.get_account()
    except (AlpacaUnauthorized, AlpacaOrderError) as exc:
        raise HTTPException(status_code=502, detail=f"broker_account: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=502, detail=f"broker_account: {exc}") from exc


@router.get("/broker/positions")
def broker_positions() -> list[dict]:
    if not _alpaca_env_present():
        return list(_MOCK_POSITIONS)
    broker = get_broker()
    try:
        return broker.get_positions()
    except (AlpacaUnauthorized, AlpacaOrderError) as exc:
        raise HTTPException(status_code=502, detail=f"broker_positions: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=502, detail=f"broker_positions: {exc}") from exc


@router.get("/broker/orders")
def broker_orders(
    status: str = Query("all"),
    limit: int = Query(50, ge=1, le=500),
) -> list[dict]:
    if not _alpaca_env_present():
        return list(_MOCK_ORDERS)[:limit]
    broker = get_broker()
    try:
        return broker.get_orders(status=status, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (AlpacaUnauthorized, AlpacaOrderError) as exc:
        raise HTTPException(status_code=502, detail=f"broker_orders: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=502, detail=f"broker_orders: {exc}") from exc
