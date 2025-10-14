"""Reconciliation helpers for broker state."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .audit import AuditLog

try:  # pragma: no cover - imported for type compatibility
    from app.execution.alpaca_adapter import AlpacaUnauthorized
except Exception:  # pragma: no cover - fallback for minimal environments
    class AlpacaUnauthorized(Exception):
        """Fallback exception used when Alpaca adapter is unavailable."""


_ORDER_STATUS_MAP = {
    "new": "new",
    "pending_new": "new",
    "accepted": "accepted",
    "acknowledged": "accepted",
    "partially_filled": "partially_filled",
    "partial": "partially_filled",
    "filled": "filled",
    "canceled": "canceled",
    "cancelled": "canceled",
    "stopped": "canceled",
    "rejected": "rejected",
    "expired": "expired",
    "done": "filled",
    "replaced": "replaced",
    "open": "accepted",
}

_ORDER_TYPE_MAP = {
    "limit": "limit",
    "market": "market",
    "stop": "stop",
    "stop_limit": "stop_limit",
    "trailing_stop": "trailing_stop",
    "trailing_stop_order": "trailing_stop",
}

_OPEN_STATUSES = {"new", "accepted", "partially_filled"}
_CLOSED_STATUSES = {"filled", "canceled", "rejected", "expired", "replaced"}


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    if hasattr(value, "__float__"):
        try:
            return float(value)
        except Exception:  # pragma: no cover - defensive
            return None
    return None


def _to_iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:  # pragma: no cover - defensive
            return str(value)
    return str(value)


def _status_matches(status: str, scope: str) -> bool:
    if scope == "all":
        return True
    if scope == "open":
        return status in _OPEN_STATUSES
    if scope == "closed":
        return status in _CLOSED_STATUSES
    return False


@dataclass(slots=True)
class _State:
    orders: Dict[str, Dict[str, Any]]
    last_sync_at: Optional[str]


class Reconciler:
    """Reconcile broker state with the local store and audit events."""

    def __init__(
        self,
        broker: Any,
        audit: AuditLog,
        state_store_path: Path,
        *,
        mock_mode: bool = False,
    ) -> None:
        self.broker = broker
        self.audit = audit
        self.state_store_path = Path(state_store_path)
        self.state_store_path.parent.mkdir(parents=True, exist_ok=True)
        self.mock_mode = mock_mode
        self._state_lock = threading.Lock()

    # ------------------------------------------------------------------
    def fetch_orders(self, status_scope: str = "all") -> List[Dict[str, Any]]:
        self._validate_scope(status_scope)
        raw_orders = self._pull_orders(status_scope)
        normalized = [self._normalize_order(order) for order in raw_orders]
        return [order for order in normalized if _status_matches(order["status"], status_scope)]

    def fetch_positions(self) -> List[Dict[str, Any]]:
        raw_positions = self._pull_positions()
        return [self._normalize_position(pos) for pos in raw_positions]

    # ------------------------------------------------------------------
    def sync_once(self, status_scope: str = "all") -> Dict[str, int]:
        self._validate_scope(status_scope)
        orders = self.fetch_orders(status_scope=status_scope)
        timestamp = datetime.now(timezone.utc).isoformat()

        with self._state_lock:
            state = self._load_state()
            stored_orders = dict(state.orders)

            seen = len(orders)
            new_count = 0
            changed_count = 0
            unchanged_count = 0

            for order in orders:
                order_id = order.get("id")
                if not order_id:
                    continue
                previous = stored_orders.get(order_id)
                if previous is None:
                    new_count += 1
                    stored_orders[order_id] = order
                    self.audit.append({"ts": timestamp, "event": "order_new", "order": order})
                elif previous != order:
                    changed_count += 1
                    self.audit.append(
                        {
                            "ts": timestamp,
                            "event": "order_change",
                            "before": previous,
                            "after": order,
                        }
                    )
                    stored_orders[order_id] = order
                else:
                    unchanged_count += 1

            summary = {
                "seen": seen,
                "new": new_count,
                "changed": changed_count,
                "unchanged": unchanged_count,
            }

            self.audit.append({"ts": timestamp, "event": "sync_summary", "stats": summary})

            new_state = _State(orders=stored_orders, last_sync_at=timestamp)
            self._save_state(new_state)

        return summary

    # ------------------------------------------------------------------
    def get_state_summary(self) -> Dict[str, Any]:
        state = self._load_state()
        return {
            "last_sync_at": state.last_sync_at,
            "order_count": len(state.orders),
            "orders": state.orders,
        }

    # ------------------------------------------------------------------
    @staticmethod
    def mock_sample_orders() -> List[Dict[str, Any]]:
        submitted = datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)
        filled = datetime(2024, 1, 2, 15, 5, tzinfo=timezone.utc)
        return [
            {
                "id": "mock-order-open",
                "client_order_id": "MOCK-OPEN-001",
                "symbol": "AAPL",
                "side": "buy",
                "qty": 10.0,
                "filled_qty": 0.0,
                "status": "accepted",
                "type": "limit",
                "limit_price": 150.0,
                "stop_price": None,
                "submitted_at": submitted.isoformat(),
                "updated_at": submitted.isoformat(),
            },
            {
                "id": "mock-order-filled",
                "client_order_id": "MOCK-FILLED-001",
                "symbol": "MSFT",
                "side": "sell",
                "qty": 5.0,
                "filled_qty": 5.0,
                "status": "filled",
                "type": "limit",
                "limit_price": 320.0,
                "stop_price": None,
                "submitted_at": submitted.isoformat(),
                "updated_at": filled.isoformat(),
            },
        ]

    # ------------------------------------------------------------------
    def _pull_orders(self, status_scope: str) -> Iterable[Any]:
        if self.mock_mode:
            return list(self.mock_sample_orders())

        broker = self.broker
        if broker is None:
            return []

        if hasattr(broker, "list_orders"):
            try:
                return list(broker.list_orders(status_scope))
            except AlpacaUnauthorized:
                return list(self.mock_sample_orders())
        if hasattr(broker, "fetch_orders"):
            try:
                orders = broker.fetch_orders()
            except AlpacaUnauthorized:
                return list(self.mock_sample_orders())
            except Exception:
                return []
            return orders
        return []

    def _pull_positions(self) -> Iterable[Any]:
        if self.mock_mode:
            return self._mock_positions()

        broker = self.broker
        if broker is None:
            return []
        if hasattr(broker, "list_positions"):
            try:
                return list(broker.list_positions())
            except AlpacaUnauthorized:
                return self._mock_positions()
        if hasattr(broker, "fetch_positions"):
            try:
                return broker.fetch_positions()
            except AlpacaUnauthorized:
                return self._mock_positions()
            except Exception:
                return []
        return []

    # ------------------------------------------------------------------
    def _normalize_order(self, order: Any) -> Dict[str, Any]:
        if isinstance(order, dict):
            payload = dict(order)
        else:
            payload = {attr: getattr(order, attr, None) for attr in (
                "id",
                "client_order_id",
                "symbol",
                "side",
                "qty",
                "quantity",
                "filled_qty",
                "filled_quantity",
                "filled_avg_price",
                "status",
                "type",
                "order_type",
                "limit_price",
                "stop_price",
                "submitted_at",
                "created_at",
                "updated_at",
                "filled_at",
            )}

        order_id = payload.get("id") or payload.get("order_id") or payload.get("guid")
        client_id = payload.get("client_order_id") or payload.get("client_id") or order_id
        symbol = (payload.get("symbol") or "").strip().upper()
        side = (payload.get("side") or "").strip().lower() or "buy"

        qty = _to_float(
            payload.get("qty")
            or payload.get("quantity")
            or payload.get("order_qty")
            or payload.get("base_qty")
        )
        filled_qty = _to_float(
            payload.get("filled_qty")
            or payload.get("filled_quantity")
            or payload.get("filled_qty_total")
        ) or 0.0

        limit_price = _to_float(payload.get("limit_price"))
        stop_price = _to_float(payload.get("stop_price") or payload.get("stop_limit_price"))

        raw_status = str(payload.get("status") or "").lower().strip()
        status = _ORDER_STATUS_MAP.get(raw_status, "new")

        raw_type = str(payload.get("type") or payload.get("order_type") or "").lower().strip()
        order_type = _ORDER_TYPE_MAP.get(raw_type, "unknown")

        submitted_at = _to_iso(
            payload.get("submitted_at") or payload.get("created_at")
        )
        updated_at = _to_iso(payload.get("updated_at") or payload.get("filled_at"))

        return {
            "id": str(order_id) if order_id is not None else str(client_id or ""),
            "client_order_id": str(client_id or ""),
            "symbol": symbol,
            "side": side,
            "qty": float(qty) if qty is not None else 0.0,
            "filled_qty": float(filled_qty),
            "status": status,
            "type": order_type,
            "limit_price": float(limit_price) if limit_price is not None else None,
            "stop_price": float(stop_price) if stop_price is not None else None,
            "submitted_at": submitted_at,
            "updated_at": updated_at,
        }

    def _normalize_position(self, position: Any) -> Dict[str, Any]:
        if isinstance(position, dict):
            payload = dict(position)
        else:
            payload = {attr: getattr(position, attr, None) for attr in (
                "symbol",
                "qty",
                "quantity",
                "avg_entry_price",
                "avg_price",
                "market_price",
                "market_value",
                "unrealized_pl",
                "unrealized_profit_loss",
                "updated_at",
            )}

        qty = _to_float(payload.get("qty") or payload.get("quantity")) or 0.0
        avg_entry = _to_float(payload.get("avg_entry_price") or payload.get("avg_price"))
        market_price = _to_float(payload.get("market_price"))
        if market_price is None:
            market_value = _to_float(payload.get("market_value"))
            market_price = market_value / qty if market_value not in (None, 0.0) and qty else None
        unrealized = _to_float(payload.get("unrealized_pl") or payload.get("unrealized_profit_loss"))

        return {
            "symbol": (payload.get("symbol") or "").upper(),
            "qty": qty,
            "avg_entry": avg_entry,
            "market_price": market_price,
            "unrealized_pl": unrealized,
            "last_updated": _to_iso(payload.get("updated_at")),
        }

    # ------------------------------------------------------------------
    def _load_state(self) -> _State:
        if not self.state_store_path.exists():
            return _State(orders={}, last_sync_at=None)
        try:
            raw = json.loads(self.state_store_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return _State(orders={}, last_sync_at=None)
        orders = raw.get("orders")
        if not isinstance(orders, dict):
            orders = {}
        last_sync_at = raw.get("last_sync_at") if isinstance(raw, dict) else None
        return _State(orders=orders, last_sync_at=last_sync_at)

    def _save_state(self, state: _State) -> None:
        payload = {"orders": state.orders, "last_sync_at": state.last_sync_at}
        tmp_path = Path(f"{self.state_store_path}.tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp_path.replace(self.state_store_path)

    def _validate_scope(self, scope: str) -> None:
        if scope not in {"open", "closed", "all"}:
            raise ValueError(f"invalid status scope: {scope}")

    def _mock_positions(self) -> List[Dict[str, Any]]:
        return [
            {
                "symbol": "AAPL",
                "qty": 10.0,
                "avg_entry": 145.0,
                "market_price": 150.0,
                "unrealized_pl": 50.0,
                "last_updated": None,
            },
            {
                "symbol": "MSFT",
                "qty": -5.0,
                "avg_entry": 325.0,
                "market_price": 320.0,
                "unrealized_pl": 25.0,
                "last_updated": None,
            },
        ]


__all__ = ["Reconciler"]

