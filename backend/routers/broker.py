"""Broker endpoints that proxy Alpaca without local caching."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query

from app.execution.alpaca_adapter import AlpacaAdapter
from core.settings import get_settings

router = APIRouter(tags=["broker"])


def alpaca(settings=Depends(get_settings)) -> AlpacaAdapter:
    alpaca_settings = settings.alpaca
    if not alpaca_settings.key_id or not alpaca_settings.secret_key:
        raise HTTPException(status_code=503, detail="Alpaca credentials unavailable")
    return AlpacaAdapter(
        base_url=alpaca_settings.base_url,
        key_id=alpaca_settings.key_id,
        secret_key=alpaca_settings.secret_key,
    )


@router.get("/account")
def account(adapter: AlpacaAdapter = Depends(alpaca)) -> Dict[str, Any]:
    return adapter.get_account()


@router.get("/positions")
def positions(adapter: AlpacaAdapter = Depends(alpaca)) -> list[dict]:
    return adapter.list_positions()


@router.get("/orders")
def orders(
    status: str = Query("all"),
    limit: int = Query(50, ge=1, le=500),
    adapter: AlpacaAdapter = Depends(alpaca),
) -> list[dict]:
    try:
        raw = adapter.list_orders(status=status, limit=limit)
    except Exception as exc:  # noqa: BLE001 - surface Alpaca errors
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return [AlpacaAdapter.normalize_order(order) for order in raw]


@router.post("/orders")
def place_order(
    order: Dict[str, Any], adapter: AlpacaAdapter = Depends(alpaca)
) -> Dict[str, Any]:
    payload = dict(order)
    payload.setdefault("client_order_id", deterministic_client_id(payload))
    try:
        created = adapter.place_order(payload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return AlpacaAdapter.normalize_order(created)


@router.delete("/orders/{order_id}")
def cancel_order(
    order_id: str, adapter: AlpacaAdapter = Depends(alpaca)
) -> Dict[str, bool]:
    try:
        adapter.cancel_order(order_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True}


def deterministic_client_id(payload: Dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()
    return f"gt-{digest[:20]}"


__all__ = [
    "router",
    "deterministic_client_id",
]
