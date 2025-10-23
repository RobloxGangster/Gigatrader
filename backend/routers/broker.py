"""Broker endpoints that proxy Alpaca without local caching."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Mapping

from fastapi import APIRouter, Depends, HTTPException, Query

from app.execution.alpaca_adapter import AlpacaAdapter, AlpacaOrderError, AlpacaUnauthorized

from backend.routers.deps import BrokerService, get_broker
from backend.services.rate_limit import record_rate_limit

router = APIRouter(tags=["broker"])


def deterministic_client_id(payload: Mapping[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()
    return f"gt-{digest[:20]}"


def _record_rate_limit(service: BrokerService) -> None:
    record_rate_limit(service.last_headers())


def alpaca(service: BrokerService = Depends(get_broker)) -> Any:
    adapter = getattr(service, "adapter", None)
    return adapter or service


@router.get("/account")
def account(service: BrokerService = Depends(get_broker)) -> Dict[str, Any]:
    try:
        data = service.get_account()
        return data
    except AlpacaUnauthorized as exc:
        raise HTTPException(status_code=401, detail="alpaca_unauthorized") from exc
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        _record_rate_limit(service)


@router.get("/positions")
def positions(service: BrokerService = Depends(get_broker)) -> list[dict]:
    try:
        return service.get_positions()
    except AlpacaUnauthorized as exc:
        raise HTTPException(status_code=401, detail="alpaca_unauthorized") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        _record_rate_limit(service)


@router.get("/orders")
def orders(
    status: str = Query("all"),
    limit: int = Query(50, ge=1, le=500),
    service: BrokerService = Depends(get_broker),
    adapter: Any = Depends(alpaca),
) -> list[dict]:
    try:
        if hasattr(adapter, "list_orders"):
            raw = adapter.list_orders(status=status, limit=limit)
        else:
            raw = service.get_orders(status=status, limit=limit)
        if raw and hasattr(AlpacaAdapter, "normalize_order"):
            return [AlpacaAdapter.normalize_order(order) for order in raw]
        return raw
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AlpacaUnauthorized as exc:
        raise HTTPException(status_code=401, detail="alpaca_unauthorized") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        _record_rate_limit(service)


@router.post("/orders")
def place_order(order: Dict[str, Any], service: BrokerService = Depends(get_broker)) -> Dict[str, Any]:
    payload = dict(order)
    payload.setdefault("client_order_id", deterministic_client_id(payload))
    adapter = service.adapter
    try:
        created = adapter.place_order(payload)
        return AlpacaAdapter.normalize_order(created) if created else created
    except AlpacaUnauthorized as exc:
        raise HTTPException(status_code=401, detail="alpaca_unauthorized") from exc
    except AlpacaOrderError as exc:
        reason: str | None = None
        if hasattr(exc, "payload") and isinstance(exc.payload, Mapping):
            reason = str(exc.payload.get("message") or exc.payload.get("error"))
        message = reason or str(exc)
        detail = {
            "status": "rejected",
            "symbol": payload.get("symbol"),
            "qty": payload.get("qty"),
            "reason": message,
        }
        status_code = getattr(exc, "status_code", 400) or 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    finally:
        _record_rate_limit(service)


@router.delete("/orders/{order_id}")
def cancel_order(order_id: str, service: BrokerService = Depends(get_broker)) -> Dict[str, bool]:
    adapter = service.adapter
    try:
        adapter.cancel_order(order_id)
        return {"ok": True}
    except AlpacaUnauthorized as exc:
        raise HTTPException(status_code=401, detail="alpaca_unauthorized") from exc
    except AlpacaOrderError as exc:
        status_code = getattr(exc, "status_code", 400) or 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    finally:
        _record_rate_limit(service)


__all__ = [
    "router",
    "deterministic_client_id",
    "alpaca",
]
