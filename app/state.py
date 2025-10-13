"""Execution state tracking and intent idempotency helpers."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, Optional

from services.risk.state import Position, StateProvider


def _model_to_dict(obj: Any) -> Dict[str, Any]:
    """Best-effort conversion of SDK models into dictionaries."""

    if obj is None:
        return {}
    if isinstance(obj, dict):
        return dict(obj)
    for attr in ("model_dump", "to_dict", "dict"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            try:
                data = fn()
            except Exception:  # noqa: BLE001 - fall back to other strategies
                continue
            if isinstance(data, dict):
                return data
    try:
        return {k: v for k, v in vars(obj).items() if not k.startswith("_")}
    except Exception:  # noqa: BLE001 - final fallback
        return {"value": obj}


def _to_float(value: Any, *, default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


@dataclass(slots=True)
class IntentRecord:
    """Lightweight tracking entry for a submitted order intent."""

    key: str
    client_order_id: str
    symbol: Optional[str] = None
    side: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    provider_order_id: Optional[str] = None


class ExecutionState(StateProvider):
    """State provider feeding risk manager + idempotent router."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._intent_by_key: Dict[str, IntentRecord] = {}
        self._intent_by_cid: Dict[str, IntentRecord] = {}
        self._open_orders: Dict[str, Dict[str, Any]] = {}
        self._positions: Dict[str, Position] = {}
        self._last_trade_ts: Dict[str, float] = {}
        self._portfolio_notional: float = 0.0
        self._account: Dict[str, Any] = {
            "id": "",
            "status": "",
            "cash": 0.0,
            "portfolio_value": 0.0,
            "equity": 0.0,
            "day_pnl": 0.0,
            "pattern_day_trader": False,
            "multiplier": 1.0,
        }

    # ------------------------------------------------------------------
    # Intent helpers
    def seen(self, key: str) -> bool:
        with self._lock:
            return key in self._intent_by_key

    def client_id_for(self, key: str) -> Optional[str]:
        with self._lock:
            record = self._intent_by_key.get(key)
            return record.client_order_id if record else None

    def remember(self, key: str, cid: str, *, symbol: Optional[str] = None, side: Optional[str] = None) -> None:
        record = IntentRecord(key=key, client_order_id=cid, symbol=symbol, side=side)
        with self._lock:
            self._intent_by_key[key] = record
            self._intent_by_cid[cid] = record
            if symbol:
                self._last_trade_ts[symbol.upper()] = record.created_at

    def map_provider_id(self, cid: str, provider_id: Optional[str]) -> None:
        with self._lock:
            record = self._intent_by_cid.get(cid)
            if record is not None:
                record.provider_order_id = provider_id

    # ------------------------------------------------------------------
    # Broker snapshots
    def update_orders(self, orders: list[Any]) -> None:
        snapshot: Dict[str, Dict[str, Any]] = {}
        with self._lock:
            for order in orders:
                data = _model_to_dict(order)
                cid = str(data.get("client_order_id") or data.get("id") or "")
                if not cid:
                    continue
                normalised = {
                    "id": str(data.get("id", "")),
                    "client_order_id": cid,
                    "symbol": str(data.get("symbol", "")).upper(),
                    "side": str(data.get("side", "")).lower(),
                    "status": str(data.get("status", "")).lower(),
                    "qty": _to_float(data.get("qty") or data.get("quantity"), default=0.0),
                    "filled_qty": _to_float(data.get("filled_qty"), default=0.0),
                    "limit_price": _to_float(data.get("limit_price")),
                    "submitted_at": data.get("submitted_at"),
                    "raw": data,
                }
                snapshot[cid] = normalised
                record = self._intent_by_cid.get(cid)
                if record is None:
                    record = IntentRecord(key=cid, client_order_id=cid, symbol=normalised.get("symbol"))
                    self._intent_by_cid[cid] = record
                    self._intent_by_key.setdefault(cid, record)
                record.provider_order_id = normalised.get("id")
                if normalised.get("symbol"):
                    self._last_trade_ts.setdefault(normalised["symbol"], record.created_at)
            self._open_orders = snapshot

    def update_positions(self, positions: list[Any]) -> None:
        mapped: Dict[str, Position] = {}
        notional = 0.0
        with self._lock:
            for pos in positions:
                data = _model_to_dict(pos)
                symbol = str(data.get("symbol", "")).upper()
                if not symbol:
                    continue
                qty = _to_float(data.get("qty") or data.get("quantity"), default=0.0) or 0.0
                market_value = _to_float(data.get("market_value"), default=0.0) or 0.0
                avg_price = _to_float(data.get("avg_entry_price"), default=0.0) or 0.0
                notional_value = market_value if market_value else abs(qty) * avg_price
                mapped[symbol] = Position(
                    symbol=symbol,
                    qty=qty,
                    notional=notional_value,
                    is_option=str(data.get("asset_class", "")).lower() == "option",
                    metadata=data,
                )
                notional += abs(notional_value)
            self._positions = mapped
            self._portfolio_notional = notional

    def update_account(self, account: Any) -> None:
        data = _model_to_dict(account)
        with self._lock:
            self._account.update(
                {
                    "id": str(data.get("id", self._account.get("id", ""))),
                    "status": str(data.get("status", self._account.get("status", ""))),
                    "cash": _to_float(data.get("cash"), default=float(self._account.get("cash", 0.0))) or 0.0,
                    "portfolio_value": _to_float(
                        data.get("portfolio_value") or data.get("equity"),
                        default=float(self._account.get("portfolio_value", 0.0)),
                    )
                    or float(self._account.get("portfolio_value", 0.0)),
                    "equity": _to_float(
                        data.get("equity") or data.get("portfolio_value"),
                        default=float(self._account.get("equity", 0.0)),
                    )
                    or float(self._account.get("equity", 0.0)),
                    "day_pnl": _to_float(
                        data.get("day_pl") or data.get("day_profit_loss"),
                        default=float(self._account.get("day_pnl", 0.0)),
                    )
                    or float(self._account.get("day_pnl", 0.0)),
                    "pattern_day_trader": bool(data.get("pattern_day_trader", self._account.get("pattern_day_trader", False))),
                    "multiplier": _to_float(
                        data.get("multiplier"),
                        default=float(self._account.get("multiplier", 1.0)),
                    )
                    or float(self._account.get("multiplier", 1.0)),
                }
            )

    # ------------------------------------------------------------------
    # Risk provider hooks
    def get_day_pnl(self) -> float:
        with self._lock:
            return float(self._account.get("day_pnl", 0.0))

    def get_positions(self) -> Dict[str, Position]:
        with self._lock:
            return dict(self._positions)

    def get_portfolio_notional(self) -> float:
        with self._lock:
            return float(self._portfolio_notional)

    def get_account_equity(self) -> Optional[float]:
        with self._lock:
            return float(self._account.get("equity", 0.0))

    def last_trade_age(self, symbol: str) -> Optional[float]:
        with self._lock:
            ts = self._last_trade_ts.get(symbol.upper())
        if ts is None:
            return None
        return max(0.0, time.time() - ts)

    # ------------------------------------------------------------------
    # Snapshots for HTTP / diagnostics
    def orders_snapshot(self) -> list[Dict[str, Any]]:
        with self._lock:
            snapshot = []
            for cid, payload in self._open_orders.items():
                record = self._intent_by_cid.get(cid)
                item = dict(payload)
                if record is not None:
                    item["intent_key"] = record.key
                    item["provider_order_id"] = record.provider_order_id
                snapshot.append(item)
            return snapshot

    def positions_snapshot(self) -> list[Dict[str, Any]]:
        with self._lock:
            snapshot = []
            for symbol, pos in self._positions.items():
                snapshot.append(
                    {
                        "symbol": symbol,
                        "qty": pos.qty,
                        "notional": pos.notional,
                        "is_option": pos.is_option,
                        "metadata": pos.metadata,
                    }
                )
            return snapshot

    def account_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._account)
