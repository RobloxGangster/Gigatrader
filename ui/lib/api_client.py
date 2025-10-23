from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Dict, Iterable, Optional, Sequence

import requests
import streamlit as st
from requests import HTTPError, Response
from urllib.parse import urljoin

DEFAULT_API = "http://127.0.0.1:8000"

DEFAULTS: tuple[str, ...] = (
    os.environ.get("API_BASE_URL") or "",
    os.environ.get("GIGATRADER_API") or "",
    os.environ.get("GIGAT_API_URL") or "",
    DEFAULT_API,
    "http://127.0.0.1:18000",
    "http://localhost:8000",
)


def _candidates() -> Iterable[str]:
    for base in DEFAULTS:
        if base:
            yield base


try:
    from .api_client import discover_api_base_url as _existing_discover  # type: ignore
except Exception:  # pragma: no cover - compatibility shim
    _existing_discover = None  # type: ignore


@lru_cache(maxsize=1)
def discover_base_url() -> str:
    """Return a usable API base URL, cached for performance."""
    if callable(_existing_discover):
        return _existing_discover()

    for candidate in _candidates():
        return candidate
    return DEFAULT_API


def reset_discovery_cache() -> None:
    """Clear the cached API base URL discovery result."""
    discover_base_url.cache_clear()  # type: ignore[attr-defined]


def _session_override() -> Optional[str]:
    try:
        value = st.session_state.get("api.base_url")
    except Exception:  # pragma: no cover - defensive guard
        return None
    if isinstance(value, str):
        value = value.strip()
        if value:
            return value
    return None


class ApiClient:
    """Very small, synchronous HTTP client wrapper used by the UI."""

    def __init__(
        self,
        base: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        bases: Optional[Iterable[Optional[str]]] = None,
        timeout: float = 10.0,
    ) -> None:
        candidates: list[Optional[str]] = [base_url or base]
        candidates.append(_session_override())
        if bases:
            candidates.extend(bases)
        candidates.extend(list(_candidates()))

        resolved = None
        for candidate in candidates:
            if not candidate:
                continue
            candidate = str(candidate).strip()
            if candidate:
                resolved = candidate.rstrip("/")
                break
        if not resolved:
            resolved = discover_base_url().rstrip("/")

        self.base_url = resolved
        self.timeout = timeout
        self._last_error: Optional[str] = None

    # -------------------------
    # Basic request helpers
    # -------------------------
    def base(self) -> str:
        return self.base_url

    def _url(self, path: str) -> str:
        path = path or ""
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base_url}/{path.lstrip('/')}"

    def request(self, method: str, path: str, **kwargs) -> Response:
        timeout = kwargs.pop("timeout", self.timeout)
        url = self._url(path)
        try:
            response = requests.request(method.upper(), url, timeout=timeout, **kwargs)
        except requests.RequestException as exc:  # pragma: no cover - network guard
            self._last_error = str(exc)
            raise

        try:
            response.raise_for_status()
        except HTTPError as exc:
            self._last_error = str(exc)
            raise

        self._last_error = None
        return response

    def _parse_response(self, response: Response) -> Any:
        if response.status_code == 204 or not response.content:
            return {}
        content_type = (response.headers.get("content-type") or "").lower()
        if "application/json" in content_type or content_type.endswith("+json"):
            try:
                return response.json()
            except ValueError:
                return response.text
        if content_type.startswith("text/"):
            return response.text
        return response.content

    def _request(self, method: str, path: str, **kwargs) -> Any:
        response = self.request(method, path, **kwargs)
        return self._parse_response(response)

    def _request_with_fallback(self, method: str, paths: Sequence[str], **kwargs) -> Any:
        last_exc: Optional[Exception] = None
        for candidate in paths:
            try:
                return self._request(method, candidate, **kwargs)
            except HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status in {404, 405}:
                    last_exc = exc
                    continue
                last_exc = exc
                break
            except requests.RequestException as exc:
                last_exc = exc
                break
        if last_exc:
            raise last_exc
        raise RuntimeError("No request paths provided")

    def get(self, path: str, **kwargs) -> Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> Response:
        return self.request("POST", path, **kwargs)

    def json_get(self, path: str, **kwargs) -> Dict[str, Any]:
        response = self.get(path, **kwargs)
        return response.json()

    def json_post(self, path: str, payload: Any, **kwargs) -> Dict[str, Any]:
        response = self.post(path, json=payload, **kwargs)
        return response.json()

    # -------------------------
    # Control Center helpers
    # -------------------------
    def is_reachable(self) -> bool:
        try:
            self.health()
        except Exception as exc:  # noqa: BLE001 - surface to caller
            self._last_error = str(exc)
            return False
        return True

    def explain_last_error(self) -> Optional[str]:
        return self._last_error

    def health(self) -> Any:
        return self._request("GET", "/health")

    def status(self) -> Any:
        return self._request("GET", "/status")

    def orchestrator_status(self) -> Any:
        return self._request("GET", "/orchestrator/status")

    def orchestrator_start(self, preset: Optional[str] = None, mode: Optional[str] = None) -> Any:
        payload: Dict[str, Any] = {}
        if preset is not None:
            payload["preset"] = preset
        if mode is not None:
            payload["mode"] = mode
        json_payload = payload or None
        try:
            return self._request("POST", "/orchestrator/start", json=json_payload)
        except HTTPError as exc:
            if exc.response is not None and exc.response.status_code in {404, 405}:
                return self._request("POST", "/paper/start", json=json_payload)
            raise

    def orchestrator_stop(self) -> Any:
        try:
            return self._request("POST", "/orchestrator/stop")
        except HTTPError as exc:
            if exc.response is not None and exc.response.status_code in {404, 405}:
                return self._request("POST", "/paper/stop")
            raise

    def orchestrator_reconcile(self) -> Any:
        try:
            return self._request("POST", "/orchestrator/reconcile")
        except HTTPError as exc:
            if exc.response is not None and exc.response.status_code in {404, 405}:
                return self._request("POST", "/reconcile")
            raise

    def strategy_config(self) -> Any:
        return self._request("GET", "/strategy/config")

    def strategy_update(self, payload: Dict[str, Any]) -> Any:
        return self._request("POST", "/strategy/config", json=payload)

    def risk_config(self) -> Any:
        return self._request("GET", "/risk/config")

    def risk_update(self, payload: Dict[str, Any]) -> Any:
        return self._request("POST", "/risk/config", json=payload)

    def risk_reset_kill_switch(self) -> Any:
        return self._request("POST", "/risk/killswitch/reset")

    def stream_status(self) -> Any:
        return self._request("GET", "/stream/status")

    def stream_start(self) -> Any:
        return self._request("POST", "/stream/start")

    def stream_stop(self) -> Any:
        return self._request("POST", "/stream/stop")

    def cancel_all_orders(self) -> Any:
        return self._request("POST", "/orders/cancel_all")

    def account(self) -> Any:
        return self._request_with_fallback("GET", ["/broker/account", "/alpaca/account"])

    def positions(self) -> Any:
        try:
            return self._request("GET", "/broker/positions")
        except HTTPError as exc:
            if exc.response is not None and exc.response.status_code in {404, 405}:
                return self._request("GET", "/positions", params={"live": True})
            raise

    def orders(self, *, status: Optional[str] = None, limit: Optional[int] = None) -> Any:
        params: Dict[str, Any] = {}
        if status is not None:
            params["status"] = status
        if limit is not None:
            params["limit"] = limit
        try:
            return self._request("GET", "/broker/orders", params=params or None)
        except HTTPError as exc:
            if exc.response is not None and exc.response.status_code in {404, 405}:
                fallback_params = dict(params) if params else {"live": True}
                return self._request("GET", "/orders", params=fallback_params)
            raise

    def pnl_summary(self) -> Any:
        return self._request("GET", "/pnl/summary")

    def exposure(self) -> Any:
        return self._request("GET", "/telemetry/exposure")

    def recent_logs(self, *, limit: int = 200) -> Any:
        try:
            return self._request("GET", "/logs/recent", params={"limit": limit})
        except HTTPError as exc:
            if exc.response is not None and exc.response.status_code in {404, 405}:
                return self._request("GET", "/logs/tail", params={"lines": limit})
            raise


@lru_cache(maxsize=1)
def get_client() -> ApiClient:
    return ApiClient()


def json_get(path: str, **kwargs) -> Dict[str, Any]:
    return get_client().json_get(path, **kwargs)


def json_post(path: str, payload: Any, **kwargs) -> Dict[str, Any]:
    return get_client().json_post(path, payload, **kwargs)


def _base_url() -> str:
    # Prefer a value the Control Center or Home set; fall back to env or discovery
    return (
        st.session_state.get("api.base_url")
        or os.getenv("API_BASE_URL")
        or discover_base_url()
    )


def build_url(path: str) -> str:
    return urljoin(_base_url().rstrip("/") + "/", path.lstrip("/"))


def get_json(path: str, params: dict | None = None, timeout: float = 8.0):
    url = build_url(path)
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    # Backend may return text lines for logs; try json first but allow text fallback in caller.
    try:
        return r.json()
    except Exception:
        return r.text


def get_text(path: str, params: dict | None = None, timeout: float = 8.0) -> str:
    url = build_url(path)
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.text


__all__ = [
    "ApiClient",
    "get_client",
    "json_get",
    "json_post",
    "discover_base_url",
    "reset_discovery_cache",
    "build_url",
    "get_json",
    "get_text",
]
