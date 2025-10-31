"""Broker endpoints that proxy Alpaca without local caching."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Mapping

from fastapi import APIRouter, Depends, HTTPException, Query

from app.execution.alpaca_adapter import AlpacaAdapter, AlpacaOrderError, AlpacaUnauthorized

from backend.routers.deps import BrokerService, get_broker, get_broker_adapter
from backend.services.rate_limit import record_rate_limit

router = APIRouter(tags=["broker"])


def deterministic_client_id(payload: Mapping[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()
    return f"gt-{digest[:20]}"


def _record_rate_limit(service: BrokerService) -> None:
    record_rate_limit(service.last_headers())


@router.get("/status")
def broker_status(
    service: BrokerService = Depends(get_broker),
    adapter: Any = Depends(get_broker_adapter),
) -> Dict[str, Any]:
    flags = getattr(service, "flags", None)
    profile = None
    dry_run = None
    if flags is not None:
        profile = "paper" if getattr(flags, "paper_trading", False) else "live"
        dry_run = getattr(flags, "dry_run", None)
    impl_name = type(adapter).__name__ if adapter is not None else type(service).__name__
    return {
        "ok": True,
        "broker": getattr(adapter, "name", getattr(flags, "broker", "unknown")),
        "impl": impl_name,
        "dry_run": getattr(adapter, "dry_run", dry_run),
        "profile": getattr(adapter, "profile", profile),
    }


@router.get("/account")
def account(service: BrokerService = Depends(get_broker)) -> Dict[str, Any]:
    try:
        data = service.get_account() or {}
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
        raw = service.get_positions()
        return raw or []
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
    adapter: Any = Depends(get_broker_adapter),
) -> list[dict]:
    try:
        if hasattr(adapter, "list_orders"):
            raw = adapter.list_orders(status=status, limit=limit)
        else:
            raw = service.get_orders(status=status, limit=limit)
        if raw and hasattr(AlpacaAdapter, "normalize_order"):
            return [AlpacaAdapter.normalize_order(order) for order in raw]
        return raw or []
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AlpacaUnauthorized as exc:
        raise HTTPException(status_code=401, detail="alpaca_unauthorized") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        _record_rate_limit(service)


@router.get("/trades")
def trades_alias(
    status: str = Query("all"),
    limit: int = Query(50, ge=1, le=500),
    service: BrokerService = Depends(get_broker),
    adapter: Any = Depends(get_broker_adapter),
) -> list[dict]:
    """Compatibility shim for legacy clients expecting /trades."""

    return orders(status=status, limit=limit, service=service, adapter=adapter)


@router.delete("/orders/{order_id}")
def cancel_order(
    order_id: str,
    service: BrokerService = Depends(get_broker),
    adapter: Any = Depends(get_broker_adapter),
) -> Dict[str, bool]:
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
    "broker_status",
]
