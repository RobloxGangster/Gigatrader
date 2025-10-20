"""Broker endpoints used by the Control Center UI."""

from fastapi import APIRouter, HTTPException, Query

from app.execution.alpaca_adapter import AlpacaOrderError, AlpacaUnauthorized

from .deps import get_broker

router = APIRouter()


@router.get("/broker/account")
def broker_account() -> dict:
    broker = get_broker()
    try:
        return broker.get_account()
    except (AlpacaUnauthorized, AlpacaOrderError) as exc:
        raise HTTPException(status_code=502, detail=f"broker_account: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=502, detail=f"broker_account: {exc}") from exc


@router.get("/broker/positions")
def broker_positions() -> list[dict]:
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
    broker = get_broker()
    try:
        return broker.get_orders(status=status, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (AlpacaUnauthorized, AlpacaOrderError) as exc:
        raise HTTPException(status_code=502, detail=f"broker_orders: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=502, detail=f"broker_orders: {exc}") from exc
