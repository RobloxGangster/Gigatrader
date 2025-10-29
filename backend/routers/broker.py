"""Broker endpoints that proxy Alpaca without local caching."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Mapping

from fastapi import APIRouter, Depends, HTTPException, Query

from app.execution.alpaca_adapter import AlpacaAdapter, AlpacaOrderError, AlpacaUnauthorized

from backend.routers.deps import BrokerService, get_broker, get_broker_adapter
from backend.services.orchestrator import record_order_attempt
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
    adapter: Any = Depends(get_broker_adapter),
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


@router.get("/trades")
def trades_alias(
    status: str = Query("all"),
    limit: int = Query(50, ge=1, le=500),
    service: BrokerService = Depends(get_broker),
    adapter: Any = Depends(get_broker_adapter),
) -> list[dict]:
    """Compatibility shim for legacy clients expecting /trades."""

    return orders(status=status, limit=limit, service=service, adapter=adapter)


@router.post("/orders")
def place_order(
    order: Dict[str, Any],
    service: BrokerService = Depends(get_broker),
    adapter: Any = Depends(get_broker_adapter),
) -> Dict[str, Any]:
    payload = dict(order)
    payload.setdefault("client_order_id", deterministic_client_id(payload))
    flags = service.flags
    try:
        if (
            getattr(flags, "broker", "").lower() == "alpaca"
            and (getattr(flags, "mock_mode", False) or getattr(flags, "dry_run", False))
        ):
            raise RuntimeError(
                "Alpaca selected but mock_mode/dry_run prevents live submission"
            )
        created = adapter.place_order(payload)
        normalized = AlpacaAdapter.normalize_order(created) if created else created
        status = str((normalized or {}).get("status", "accepted")).lower()
        accepted = status not in {"rejected", "canceled", "cancelled", "error"}
        record_order_attempt(
            symbol=payload.get("symbol"),
            qty=payload.get("qty"),
            side=payload.get("side"),
            sent=True,
            accepted=accepted,
            reason=None if accepted else status,
            broker_impl=type(adapter).__name__,
        )
        return normalized
    except RuntimeError as exc:
        record_order_attempt(
            symbol=payload.get("symbol"),
            qty=payload.get("qty"),
            side=payload.get("side"),
            sent=False,
            accepted=False,
            reason=str(exc),
            broker_impl=type(adapter).__name__,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AlpacaUnauthorized as exc:
        record_order_attempt(
            symbol=payload.get("symbol"),
            qty=payload.get("qty"),
            side=payload.get("side"),
            sent=False,
            accepted=False,
            reason="alpaca_unauthorized",
            broker_impl=type(adapter).__name__,
        )
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
        record_order_attempt(
            symbol=payload.get("symbol"),
            qty=payload.get("qty"),
            side=payload.get("side"),
            sent=True,
            accepted=False,
            reason=message,
            broker_impl=type(adapter).__name__,
        )
        raise HTTPException(status_code=status_code, detail=detail) from exc
    finally:
        _record_rate_limit(service)


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
