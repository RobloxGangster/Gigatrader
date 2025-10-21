"""HTTP adapter for interacting with Alpaca's REST API."""

from __future__ import annotations

import logging
import os
import random
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
        max_attempts: int = 4,
        backoff_base: float = 0.5,
        backoff_cap: float = 8.0,
    ) -> None:
        paper_base = os.getenv("ALPACA_PAPER_BASE", "https://paper-api.alpaca.markets")
        live_base = os.getenv("ALPACA_LIVE_BASE", "https://api.alpaca.markets")
        env_base = os.getenv("ALPACA_BASE_URL") or os.getenv("APCA_API_BASE_URL")
        resolved_base = base_url or env_base or paper_base
        resolved_base = resolved_base.rstrip("/") or paper_base.rstrip("/")

        key_id = (
            key_id
            or os.getenv("ALPACA_API_KEY")
            or os.getenv("ALPACA_KEY_ID")
            or os.getenv("ALPACA_API_KEY_ID")
            or os.getenv("APCA_API_KEY_ID")
        )
        secret_key = (
            secret_key
            or os.getenv("ALPACA_API_SECRET")
            or os.getenv("ALPACA_SECRET_KEY")
            or os.getenv("ALPACA_API_SECRET_KEY")
            or os.getenv("APCA_API_SECRET_KEY")
        )

        # Keep the live endpoint when explicitly requested, otherwise default to paper.
        resolved_mode = os.getenv("BROKER_MODE", "paper").strip().lower()
        if resolved_mode == "live" and base_url is None and env_base is None:
            resolved_base = live_base.rstrip("/")

        self.base = resolved_base
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
        self._key_id = key_id or ""
        self._secret_key = secret_key or ""
        self._max_attempts = max(1, int(max_attempts))
        self._backoff_base = max(0.1, float(backoff_base))
        self._backoff_cap = max(self._backoff_base, float(backoff_cap))

    # ------------------------------------------------------------------
    # Public Alpaca REST helpers
    # ------------------------------------------------------------------
    def is_configured(self) -> bool:
        return bool(self._key_id and self._secret_key)

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
        return self._post(
            "/v2/orders",
            json=dict(payload),
            idempotency_key=str(payload["client_order_id"]),
        )

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
    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
        retry: bool = True,
        **kwargs: Any,
    ) -> requests.Response:
        url = f"{self.base}{path}"
        attempt = 0
        backoff = self._backoff_base
        merged_headers = dict(headers or {})
        while True:
            response = self.sess.request(
                method,
                url,
                timeout=self.timeout,
                headers=merged_headers or None,
                **kwargs,
            )
            self._audit(method, url, kwargs, response)
            if not retry:
                return response
            if response.status_code in {429, 500, 502, 503, 504} and attempt < self._max_attempts - 1:
                sleep_for = backoff + random.uniform(0, backoff)
                time.sleep(min(sleep_for, self._backoff_cap))
                backoff = min(backoff * 2, self._backoff_cap)
                attempt += 1
                continue
            return response

    def _get(self, path: str, **kwargs) -> Any:
        response = self._request("GET", path, **kwargs)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:  # pragma: no cover - network failure path
            raise _map_http_error(response, exc) from exc
        return response.json()

    def _post(
        self, path: str, *, idempotency_key: str | None = None, **kwargs: Any
    ) -> Any:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        response = self._request("POST", path, headers=headers, **kwargs)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:  # pragma: no cover - network failure path
            raise _map_http_error(response, exc) from exc
        return response.json()

    def _delete(self, path: str, **kwargs) -> Any:
        response = self._request("DELETE", path, **kwargs)
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
