from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Literal

from fastapi import APIRouter, HTTPException, Query, Request

from alpaca.trading.enums import QueryOrderStatus
from alpaca.trading.requests import GetOrdersRequest

from core.broker_config import is_mock

from .alpaca_client import get_trading_client

logger = logging.getLogger(__name__)


router = APIRouter()


def pull_orders() -> List[Dict[str, Any]]:
    tc = get_trading_client()
    orders = tc.get_orders(GetOrdersRequest(status=QueryOrderStatus.ALL))
    out: List[Dict[str, Any]] = []
    for o in orders:
        out.append(o.__dict__.get("_raw", {}))
    return out


def pull_positions() -> List[Dict[str, Any]]:
    tc = get_trading_client()
    positions = tc.get_all_positions()
    return [p.__dict__.get("_raw", {}) for p in positions]


def pull_account() -> Dict[str, Any]:
    tc = get_trading_client()
    acc = tc.get_account()
    return acc.__dict__.get("_raw", {})


# no-op stubs if MOCK
def pull_all_if_live() -> Dict[str, Any]:
    mock_env = os.getenv("MOCK_MODE", "").strip().lower()
    if is_mock() or mock_env in {"1", "true", "yes", "on"}:
        return {"mode": "mock", "orders": [], "positions": [], "account": {}}
    try:
        return {
            "mode": "paper",
            "orders": pull_orders(),
            "positions": pull_positions(),
            "account": pull_account(),
        }
    except Exception as exc:  # pragma: no cover - defensive guard
        return {"mode": "error", "error": str(exc), "orders": [], "positions": [], "account": {}}


def _get_reconciler(request: Request) -> Any:
    reconciler = getattr(request.app.state, "reconciler", None)
    if reconciler is None:
        raise HTTPException(status_code=503, detail="reconciler not configured")
    return reconciler


def _get_audit_log(request: Request) -> Any:
    return getattr(request.app.state, "audit_log", None)


def _get_reconcile_broker(request: Request) -> Any:
    broker = getattr(request.app.state, "reconcile_broker", None)
    if broker is None:
        raise HTTPException(status_code=503, detail="reconcile broker not configured")
    return broker


def _maybe_update_orders(request: Request, orders: List[Dict[str, Any]]) -> None:
    state = getattr(request.app.state, "execution_state", None)
    if state is None:
        return
    try:
        state.update_orders(orders)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("execution state update failed: %s", exc)


def _maybe_update_positions(request: Request, positions: List[Dict[str, Any]]) -> None:
    state = getattr(request.app.state, "execution_state", None)
    if state is None:
        return
    try:
        state.update_positions(positions)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("execution state positions update failed: %s", exc)


@router.get("/health", summary="Reconcile service health")
def reconcile_health() -> Dict[str, bool]:
    return {"ok": True}


@router.get("/status", summary="Reconcile service status")
def reconcile_status() -> Dict[str, bool]:
    return reconcile_health()


@router.post("/run", summary="Trigger a reconciliation pass")
def reconcile_run(request: Request) -> Dict[str, Any]:
    try:
        snapshot = pull_all_if_live()
    except Exception as exc:  # pragma: no cover - network path
        raise HTTPException(status_code=502, detail=f"reconcile failed: {exc}") from exc

    orders = snapshot.get("orders", []) if isinstance(snapshot, dict) else []
    positions = snapshot.get("positions", []) if isinstance(snapshot, dict) else []
    _maybe_update_orders(request, orders)
    _maybe_update_positions(request, positions)
    return {"ok": True, "snapshot": snapshot}


@router.post("/", summary="Trigger a reconciliation pass (root)")
def reconcile_now(request: Request) -> Dict[str, Any]:
    """Compatibility endpoint mirroring the historic root POST behaviour."""

    if os.getenv("MOCK_MODE", "").strip().lower() in {"1", "true", "yes", "on"}:
        snapshot = pull_all_if_live()
        return {"ok": True, "snapshot": snapshot}
    return reconcile_run(request)


@router.post("/sync")
def reconcile_sync(
    request: Request, status: Literal["open", "closed", "all"] = Query("all")
) -> Dict[str, Any]:
    reconciler = _get_reconciler(request)
    try:
        summary = reconciler.sync_once(status_scope=status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if os.getenv("MOCK_MODE", "true").lower() in {
        "1",
        "true",
        "on",
        "yes",
    }:
        try:
            reconciler.seed_mock_order()
        except Exception:  # pragma: no cover - defensive
            pass
    return summary


@router.get("/audit-tail")
def audit_tail(
    request: Request, n: int = Query(50, ge=0, le=500)
) -> List[Dict[str, Any]]:
    if n <= 0:
        return []
    audit_log = _get_audit_log(request)
    if audit_log is None:
        return []
    try:
        return audit_log.tail(n)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("audit tail read failed: %s", exc)
        return []


@router.get("/audit_tail")
def audit_tail_compat(request: Request, n: int = Query(50, ge=0, le=500)):
    return audit_tail(request, n)


@router.post("/cancel-all")
def cancel_all(request: Request) -> Dict[str, Any]:
    broker = _get_reconcile_broker(request)
    try:
        result = broker.cancel_all()
        if isinstance(result, dict):
            return result
        return {"canceled": int(result or 0)}
    except Exception as exc:  # pragma: no cover - defensive
        if exc.__class__.__name__ == "AlpacaUnauthorized":
            return {"error": "alpaca_unauthorized"}
        return {"error": str(exc)}


@router.get("/orders")
def list_orders(
    request: Request, status: Literal["open", "closed", "all"] = Query("all")
) -> List[Dict[str, Any]]:
    reconciler = _get_reconciler(request)
    try:
        normalized_orders = reconciler.fetch_orders(status_scope=status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _maybe_update_orders(request, normalized_orders)
    return normalized_orders


@router.get("/positions")
def list_positions(request: Request) -> List[Dict[str, Any]]:
    reconciler = _get_reconciler(request)
    positions = reconciler.fetch_positions()
    _maybe_update_positions(request, positions)
    return positions


__all__ = ["router"]
