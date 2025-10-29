"""Telemetry endpoints exposed to the Control Center."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from fastapi import APIRouter, Depends

from backend.routers.deps import (
    BrokerService,
    MetricsService,
    RiskConfigService,
    get_broker,
    get_metrics,
    get_orchestrator,
    get_risk_manager,
)
from backend.services.orchestrator import OrchestratorSupervisor

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


def _safe_float(value: Any, *, default: float | None = 0.0) -> float | None:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, *, default: int | None = 0) -> int | None:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _as_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        text = str(value)
    except Exception:  # pragma: no cover - defensive
        return None
    return text or None


def _extract_first(mapping: Mapping[str, Any], keys: Sequence[str], *, default: Any = None) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return default


def _normalize_position(raw: Mapping[str, Any]) -> Dict[str, Any]:
    symbol = _extract_first(
        raw,
        ("symbol", "asset_symbol"),
        default=(raw.get("asset") or {}).get("symbol") if isinstance(raw.get("asset"), Mapping) else None,
    )
    qty = _safe_float(
        _extract_first(raw, ("qty", "quantity", "position_qty", "filled_qty")),
        default=0.0,
    )
    avg_price = _safe_float(
        _extract_first(raw, ("avg_entry_price", "avg_price", "average_price")),
        default=0.0,
    )
    market_price = _safe_float(
        _extract_first(
            raw,
            (
                "current_price",
                "market_price",
                "last_price",
                "price",
                "latest_price",
                "unrealized_intraday_price",
            ),
        ),
        default=0.0,
    )
    unrealized_pl = _safe_float(
        _extract_first(
            raw,
            (
                "unrealized_pl",
                "unrealized_intraday_pl",
                "unrealized_day_pl",
                "unrealized_plpc",
            ),
        ),
        default=0.0,
    )
    return {
        "symbol": str(symbol or "?").upper(),
        "qty": qty or 0.0,
        "avg_price": avg_price or 0.0,
        "market_price": market_price or 0.0,
        "unrealized_pl": unrealized_pl or 0.0,
    }


def _normalize_orchestrator(snapshot: Mapping[str, Any] | None) -> Dict[str, Any]:
    if not isinstance(snapshot, Mapping):
        snapshot = {}
    state_raw = str(snapshot.get("state") or "stopped").lower()
    state = "running" if state_raw == "running" else "stopped"
    if state_raw == "stopping":
        state = "stopped"
    payload = {
        "state": state,
        "last_error": snapshot.get("last_error"),
        "last_heartbeat": _as_iso(snapshot.get("last_heartbeat")),
        "can_trade": bool(snapshot.get("can_trade")),
        "trade_guard_reason": snapshot.get("trade_guard_reason"),
        "kill_switch_engaged": bool(snapshot.get("kill_switch_engaged")),
        "kill_switch_reason": snapshot.get("kill_switch_reason"),
    }
    return payload


def _normalize_risk(
    risk_snapshot: Mapping[str, Any] | None,
    orch_snapshot: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    if not isinstance(risk_snapshot, Mapping):
        risk_snapshot = {}
    if not isinstance(orch_snapshot, Mapping):
        orch_snapshot = {}
    kill_engaged = bool(orch_snapshot.get("kill_switch_engaged"))
    reason = orch_snapshot.get("kill_switch_reason")
    daily_loss = _safe_float(risk_snapshot.get("daily_loss_limit"), default=0.0)
    max_notional = _safe_float(
        risk_snapshot.get("portfolio_notional") or risk_snapshot.get("max_portfolio_notional"),
        default=0.0,
    )
    max_positions = _safe_int(risk_snapshot.get("max_positions"), default=0) or 0
    cooldown_active = bool(risk_snapshot.get("cooldown_active"))
    if not cooldown_active:
        cooldown_seconds = _safe_int(risk_snapshot.get("cooldown_sec"), default=0) or 0
        cooldown_active = cooldown_seconds > 0
    return {
        "kill_switch_engaged": kill_engaged,
        "kill_switch_reason": reason,
        "daily_loss_limit": daily_loss or 0.0,
        "max_portfolio_notional": max_notional or 0.0,
        "max_positions": max_positions,
        "cooldown_active": cooldown_active,
    }


def _normalize_trade(raw: Mapping[str, Any]) -> Dict[str, Any]:
    symbol = _extract_first(raw, ("symbol", "asset_symbol"), default="")
    side = str(_extract_first(raw, ("side", "order_side"), default="")).lower() or None
    qty_value = _extract_first(raw, ("filled_qty", "qty", "quantity"))
    qty = _safe_float(qty_value, default=None)
    limit_price = _safe_float(
        _extract_first(raw, ("limit_price", "limit", "limit_price_per_share")),
        default=None,
    )
    fill_price = _safe_float(
        _extract_first(
            raw,
            (
                "filled_avg_price",
                "avg_fill_price",
                "average_price",
                "fill_price",
            ),
        ),
        default=None,
    )
    order_type = _extract_first(
        raw,
        ("order_type", "type", "order_class", "class"),
        default=None,
    )
    status = str(_extract_first(raw, ("status",), default="")).lower() or None
    ts_value = _extract_first(
        raw,
        (
            "ts",
            "filled_at",
            "updated_at",
            "submitted_at",
            "created_at",
        ),
        default=None,
    )
    broker_order_id = _extract_first(raw, ("id", "order_id", "client_order_id"), default=None)
    return {
        "ts": _as_iso(ts_value),
        "symbol": str(symbol or "").upper(),
        "side": side,
        "qty": qty,
        "order_type": order_type.lower() if isinstance(order_type, str) else order_type,
        "limit_price": limit_price,
        "status": status,
        "fill_price": fill_price,
        "broker_order_id": broker_order_id,
    }


def _coerce_positions(raw_positions: Iterable[Any]) -> List[Dict[str, Any]]:
    positions: List[Dict[str, Any]] = []
    for item in raw_positions or []:
        if isinstance(item, Mapping):
            positions.append(_normalize_position(item))
    return positions


def _coerce_trades(raw_trades: Iterable[Any]) -> List[Dict[str, Any]]:
    trades: List[Dict[str, Any]] = []
    for item in raw_trades or []:
        if isinstance(item, Mapping):
            trades.append(_normalize_trade(item))
    return trades


@router.get("/metrics")
def telemetry_metrics(
    broker: BrokerService = Depends(get_broker),
    orch: OrchestratorSupervisor = Depends(get_orchestrator),
    risk_manager: RiskConfigService = Depends(get_risk_manager),
) -> Dict[str, Any]:
    try:
        account = broker.get_account()
    except Exception:  # pragma: no cover - defensive broker guard
        account = {}

    if not isinstance(account, Mapping):
        account = {}

    try:
        raw_positions = broker.get_positions()
    except Exception:  # pragma: no cover - defensive broker guard
        raw_positions = []

    try:
        orch_snapshot = orch.status()
    except Exception:
        orch_snapshot = {}

    try:
        risk_snapshot = risk_manager.snapshot()
    except Exception:
        risk_snapshot = {}

    equity = _safe_float(
        _extract_first(account, ("equity", "portfolio_value", "account_equity")),
        default=0.0,
    )
    buying_power = _safe_float(
        _extract_first(account, ("buying_power", "cash", "available_funds")),
        default=0.0,
    )
    day_pl = _safe_float(account.get("day_pl"), default=None)
    if day_pl is None:
        day_pl = _safe_float(account.get("daytrade_pl"), default=None)
    if day_pl is None:
        realized = _safe_float(account.get("realized_pl"), default=0.0) or 0.0
        unrealized = _safe_float(
            _extract_first(account, ("unrealized_pl", "unrealized_intraday_pl")),
            default=0.0,
        ) or 0.0
        day_pl = realized + unrealized
    if day_pl is None:
        day_pl = 0.0

    positions = _coerce_positions(raw_positions if isinstance(raw_positions, Iterable) else [])
    orchestrator_payload = _normalize_orchestrator(orch_snapshot)
    risk_payload = _normalize_risk(risk_snapshot, orch_snapshot)

    return {
        "equity": equity or 0.0,
        "buying_power": buying_power or 0.0,
        "day_pl": day_pl or 0.0,
        "positions": positions,
        "risk": risk_payload,
        "orchestrator": orchestrator_payload,
    }


@router.get("/trades")
def telemetry_trades(
    broker: BrokerService = Depends(get_broker),
    orch: OrchestratorSupervisor = Depends(get_orchestrator),
) -> List[Dict[str, Any]]:
    try:
        raw_trades: Iterable[Any]
        recent = getattr(orch, "recent_trades", None)
        if callable(recent):
            raw_trades = recent() or []
        else:
            raw_buffer = getattr(orch, "recent_trades", None)
            if isinstance(raw_buffer, Iterable):
                raw_trades = raw_buffer
            else:
                raw_trades = broker.get_orders(status="all", limit=50)
    except Exception:
        try:
            raw_trades = broker.get_orders(status="all", limit=50)
        except Exception:
            raw_trades = []

    if not isinstance(raw_trades, Iterable):
        raw_trades = []

    return _coerce_trades(raw_trades)


@router.get("/exposure")
def telemetry_exposure(metrics: MetricsService = Depends(get_metrics)) -> Dict[str, Any]:
    try:
        return metrics.exposure()
    except Exception:  # pragma: no cover - defensive exposure guard
        return {"net": 0.0, "gross": 0.0, "by_symbol": []}


__all__ = ["router"]
