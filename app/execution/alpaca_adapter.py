"""HTTP adapter for interacting with Alpaca's REST API."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Iterable, Mapping, Optional

import requests

from services.ops.alerts import audit_log


class AlpacaUnauthorized(Exception):
    """Raised when Alpaca credentials are invalid."""


class AlpacaOrderError(Exception):
    """Raised when Alpaca rejects an order payload."""


log = logging.getLogger(__name__)


_STATUS_MAP = {
    "accepted": "accepted",
    "accepted_for_bidding": "accepted",
    "calculated": "accepted",
    "canceled": "canceled",
    "done_for_day": "canceled",
    "expired": "expired",
    "filled": "filled",
    "new": "new",
    "open": "accepted",
    "partially_filled": "partially_filled",
    "pending_cancel": "accepted",
    "pending_new": "accepted",
    "pending_replace": "accepted",
    "rejected": "rejected",
    "replaced": "accepted",
    "stopped": "rejected",
    "suspended": "rejected",
}


class AlpacaAdapter:
    """Minimal REST client used by the backend, orchestrator and UI."""

    def __init__(
        self,
        base_url: str | None = None,
        key_id: str | None = None,
        secret_key: str | None = None,
        *,
        timeout: float = 10.0,
        session: Optional[requests.Session] = None,
    ) -> None:
        base_url = (
            base_url
            or os.getenv("ALPACA_BASE_URL")
            or os.getenv("APCA_API_BASE_URL")
            or "https://paper-api.alpaca.markets"
        )
        key_id = (
            key_id
            or os.getenv("ALPACA_KEY_ID")
            or os.getenv("ALPACA_API_KEY_ID")
            or os.getenv("APCA_API_KEY_ID")
        )
        secret_key = (
            secret_key
            or os.getenv("ALPACA_SECRET_KEY")
            or os.getenv("ALPACA_API_SECRET_KEY")
            or os.getenv("APCA_API_SECRET_KEY")
        )
        self.base = (base_url or "https://paper-api.alpaca.markets").rstrip("/")
        self.timeout = timeout
        self.sess = session or requests.Session()
        self.sess.headers.update(
            {
                "APCA-API-KEY-ID": key_id or "",
                "APCA-API-SECRET-KEY": secret_key or "",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )
        self._key_id_tail = (key_id or "")[-4:] or None

    # ------------------------------------------------------------------
    # Public Alpaca REST helpers
    # ------------------------------------------------------------------
    def get_account(self) -> Dict[str, Any]:
        return self._get("/v2/account")

    def list_positions(self) -> list[dict]:
        data = self._get("/v2/positions")
        return list(data) if isinstance(data, Iterable) else []

    def list_orders(self, *, status: str = "all", limit: int = 50) -> list[dict]:
        payload = {"status": status, "limit": int(limit)}
        data = self._get("/v2/orders", params=payload)
        return list(data) if isinstance(data, Iterable) else []

    def get_order(self, order_id: str) -> Dict[str, Any]:
        return self._get(f"/v2/orders/{order_id}")

    def place_order(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        if "client_order_id" not in payload:
            raise ValueError("client_order_id is required")
        return self._post("/v2/orders", json=dict(payload))

    def cancel_order(self, order_id: str) -> bool:
        self._delete(f"/v2/orders/{order_id}")
        return True

    # ------------------------------------------------------------------
    # Compatibility helpers for legacy callers
    # ------------------------------------------------------------------
    def fetch_account(self) -> Dict[str, Any]:
        return self.get_account()

    def fetch_positions(self) -> list[dict]:
        return self.list_positions()

    def fetch_orders(self, *, status: str = "all", limit: int = 50) -> list[dict]:
        return self.list_orders(status=status, limit=limit)

    @staticmethod
    def map_order_state(status: str | None) -> str:
        if not status:
            return "new"
        return _STATUS_MAP.get(status.lower(), status.lower())

    @staticmethod
    def normalize_order(order: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "id": order.get("id"),
            "client_order_id": order.get("client_order_id"),
            "symbol": order.get("symbol"),
            "qty": float(order.get("qty", 0) or order.get("quantity", 0) or 0),
            "filled_qty": float(
                order.get("filled_qty", 0) or order.get("filled_quantity", 0) or 0
            ),
            "status": AlpacaAdapter.map_order_state(order.get("status")),
            "side": order.get("side"),
            "type": order.get("type"),
            "limit_price": _safe_float(order.get("limit_price") or order.get("limit")),
            "stop_price": _safe_float(order.get("stop_price") or order.get("stop")),
            "avg_fill_price": _safe_float(order.get("filled_avg_price")),
            "submitted_at": order.get("submitted_at") or order.get("created_at"),
            "updated_at": order.get("updated_at"),
        }

    # ------------------------------------------------------------------
    # Internal HTTP helpers with audit logging
    # ------------------------------------------------------------------
    def _get(self, path: str, **kwargs) -> Any:
        url = f"{self.base}{path}"
        response = self.sess.get(url, timeout=self.timeout, **kwargs)
        self._audit("GET", url, kwargs, response)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:  # pragma: no cover - network failure path
            raise _map_http_error(response, exc) from exc
        return response.json()

    def _post(self, path: str, **kwargs) -> Any:
        url = f"{self.base}{path}"
        response = self.sess.post(url, timeout=self.timeout, **kwargs)
        self._audit("POST", url, kwargs, response)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:  # pragma: no cover - network failure path
            raise _map_http_error(response, exc) from exc
        return response.json()

    def _delete(self, path: str, **kwargs) -> Any:
        url = f"{self.base}{path}"
        response = self.sess.delete(url, timeout=self.timeout, **kwargs)
        self._audit("DELETE", url, kwargs, response)
        if response.status_code not in (200, 204):
            try:
                response.raise_for_status()
            except requests.HTTPError as exc:  # pragma: no cover - network failure path
                raise _map_http_error(response, exc) from exc
        return True

    def _audit(
        self,
        method: str,
        url: str,
        kwargs: Mapping[str, Any],
        response: requests.Response,
    ) -> None:
        payload = {
            "broker": "alpaca",
            "method": method,
            "url": url,
            "status": response.status_code,
            "ok": response.ok,
            "key_tail": self._key_id_tail,
            "ts": time.time(),
        }
        try:
            audit_log(payload)
        except Exception:  # noqa: BLE001 - audit logging must never break requests
            log.exception("failed to emit audit log")


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _map_http_error(response: requests.Response, exc: requests.HTTPError) -> Exception:
    if response.status_code in {401, 403}:
        return AlpacaUnauthorized(str(exc))
    return AlpacaOrderError(str(exc))


__all__ = ["AlpacaAdapter"]
