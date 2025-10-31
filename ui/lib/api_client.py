from __future__ import annotations

"""Small HTTP client helpers used by the Streamlit UI."""

import os
from typing import Any, Dict, Iterable, Optional, Sequence

import requests
import streamlit as st
from requests import HTTPError, Response
from urllib.parse import urljoin

_DEFAULT_BASES: Sequence[Optional[str]] = (
    os.getenv("BACKEND_BASE"),
    os.getenv("GT_API_BASE_URL"),
    "http://127.0.0.1:8000",
    "http://localhost:8000",
)

_ADDITIONAL_ENV_VARS: Sequence[str] = (
    "API_BASE_URL",
    "GIGATRADER_API",
    "GIGAT_API_URL",
)

_DISCOVERED_BASE_URL: Optional[str] = None


def _env_backend_base() -> str:
    for candidate in _DEFAULT_BASES:
        if candidate:
            return str(candidate).strip().rstrip("/") or "http://127.0.0.1:8000"
    return "http://127.0.0.1:8000"


def _sanitize_base(candidate: Optional[str]) -> Optional[str]:
    if not candidate:
        return None
    base = str(candidate).strip().rstrip("/")
    return base or None


def discover_base_url() -> str:
    """Return the first reachable backend base URL, caching the result."""

    global _DISCOVERED_BASE_URL
    if _DISCOVERED_BASE_URL:
        return _DISCOVERED_BASE_URL

    candidates: list[Optional[str]] = []
    try:
        session_value = st.session_state.get("backend_base")  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - defensive for older Streamlit builds
        session_value = None
    candidates.append(session_value)
    candidates.append(_session_override())
    candidates.extend(candidate for candidate in _DEFAULT_BASES if candidate)

    # Ensure we always have at least the environment fallback
    if not any(candidates):
        candidates.append(_env_backend_base())

    for candidate in candidates:
        base = _sanitize_base(candidate)
        if not base:
            continue
        try:
            response = requests.get(f"{base}/health", timeout=2)
        except requests.RequestException:
            continue
        if response.ok:
            _DISCOVERED_BASE_URL = base
            try:
                st.session_state["backend_base"] = base  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover - streamlit not initialised
                pass
            return base

    fallback = _sanitize_base(candidates[0]) if candidates else None
    if not fallback:
        fallback = _env_backend_base()
    _DISCOVERED_BASE_URL = fallback
    try:
        st.session_state["backend_base"] = fallback  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - streamlit not initialised
        pass
    return fallback


def reset_discovery_cache() -> None:
    """Clear any cached base URL discovery result."""

    global _DISCOVERED_BASE_URL
    _DISCOVERED_BASE_URL = None


def _session_override() -> Optional[str]:
    try:
        value = st.session_state.get("api.base_url")
    except Exception:  # pragma: no cover - defensive for older Streamlit builds
        value = None
    if isinstance(value, str) and value.strip():
        return value.strip()
    for name in _ADDITIONAL_ENV_VARS:
        env_value = os.getenv(name)
        if env_value:
            return env_value
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
        try:
            if "backend_base" not in st.session_state:  # type: ignore[attr-defined]
                st.session_state["backend_base"] = discover_base_url()  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - streamlit not initialised
            pass
        primary = base_url or base or discover_base_url()

        self.timeout = timeout
        self.base_url = self._resolve_base_url(primary, bases)
        self._last_error: Optional[str] = None

    # -------------------------
    # Base URL helpers
    # -------------------------
    def _resolve_base_url(
        self, primary: Optional[str], bases: Optional[Iterable[Optional[str]]]
    ) -> str:
        candidates: list[Optional[str]] = [primary, _session_override()]
        if bases:
            candidates.extend(bases)
        candidates.append(discover_base_url())

        for candidate in candidates:
            base = _sanitize_base(candidate)
            if base:
                return base
        return discover_base_url()

    @staticmethod
    def _sanitize_base(candidate: Optional[str]) -> Optional[str]:
        return _sanitize_base(candidate)

    def base(self) -> str:
        return self.base_url

    # -------------------------
    # Core request helpers
    # -------------------------
    def _build_url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base_url}/{path.lstrip('/')}"

    @staticmethod
    def _prepare_query(params: Dict[str, Any]) -> Dict[str, Any] | None:
        query = params.pop("params", None)
        if query is None:
            return params or None
        if isinstance(query, dict):
            merged = dict(query)
            merged.update(params)
            return merged
        return params or None

    def _request(self, method: str, path: str, **kwargs: Any) -> Response:
        timeout = kwargs.pop("timeout", self.timeout)
        url = self._build_url(path)
        try:
            response = requests.request(method.upper(), url, timeout=timeout, **kwargs)
        except requests.RequestException as exc:  # pragma: no cover - network guard
            self._last_error = str(exc)
            raise

        if response.status_code >= 400:
            body = (response.text or "").strip()
            reason = f"{response.status_code} {response.reason}".strip()
            message = f"{reason}: {body}" if body else reason
            error = HTTPError(message, response=response)
            self._last_error = message
            raise error

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

    def request(self, method: str, path: str, **kwargs: Any) -> Response:
        return self._request(method, path, **kwargs)

    def get(self, path: str, *, default: Any = None, **params: Any) -> Any:
        query = self._prepare_query(params)
        try:
            response = self._request("GET", path, params=query)
        except HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in {404, 405}:
                self._last_error = None
                return default if default is not None else {}
            self._last_error = str(exc)
            raise
        parsed = self._parse_response(response)
        if parsed is None and default is not None:
            return default
        return parsed

    def post(self, path: str, json: Any | None = None, **kwargs: Any) -> Any:
        request_kwargs = dict(kwargs)
        if json is not None:
            request_kwargs["json"] = json
        response = self._request("POST", path, **request_kwargs)
        return self._parse_response(response)

    # -------------------------
    # Convenience helpers used across the UI
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
        data = self.get("/health", default={})
        if isinstance(data, dict):
            return data
        return {"status": data}

    def pacing(self) -> Any:
        payload = self.get("/pacing", default={})
        return payload if isinstance(payload, dict) else {"raw": payload}

    def logs_recent(self, limit: int = 200) -> Any:
        try:
            data = self.get("/logs/recent", default=[], limit=limit)
        except HTTPError as exc:
            if exc.response is not None and exc.response.status_code in {404, 405}:
                return self.get("/logs", default=[], tail=limit)
            raise
        return data

    def recent_logs(self, *, limit: int = 200) -> Any:
        return self.logs_recent(limit=limit)

    def status(self) -> Any:
        return self.get("/status", default={})

    def broker_status(self) -> Any:
        payload = self.get("/broker/status", default={})
        if isinstance(payload, dict):
            return payload
        return {"raw": payload}

    def orchestrator_status(self) -> Any:
        return self.get("/orchestrator/status", default={})

    def orchestrator_debug(self) -> Any:
        return self.get("/orchestrator/debug", default={})

    def orchestrator_start(
        self,
        preset: Optional[str] = None,
        mode: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Any:
        payload: Dict[str, Any] = {}
        if preset is not None:
            payload["preset"] = preset
        if mode is not None:
            payload["mode"] = mode
        if request_id is not None:
            payload["request_id"] = request_id
        try:
            return self.post("/orchestrator/start", json=payload or None)
        except HTTPError as exc:
            if exc.response is not None and exc.response.status_code in {404, 405}:
                return self.post("/paper/start", json=payload or None)
            raise

    def orchestrator_stop(self, request_id: Optional[str] = None) -> Any:
        payload: Dict[str, Any] | None = None
        if request_id is not None:
            payload = {"request_id": request_id}
        try:
            return self.post("/orchestrator/stop", json=payload)
        except HTTPError as exc:
            if exc.response is not None and exc.response.status_code in {404, 405}:
                return self.post("/paper/stop", json=payload)
            raise

    def orchestrator_reset_kill_switch(self) -> Any:
        try:
            return self.post("/orchestrator/reset_kill_switch")
        except HTTPError as exc:
            if exc.response is not None and exc.response.status_code in {404, 405}:
                return self.post("/risk/killswitch/reset")
            raise

    def orchestrator_reconcile(self) -> Any:
        try:
            return self.post("/orchestrator/reconcile")
        except HTTPError as exc:
            if exc.response is not None and exc.response.status_code in {404, 405}:
                return self.post("/reconcile")
            raise

    def debug_runtime(self) -> Dict[str, Any]:
        payload = self.get("/debug/runtime", default={})
        if isinstance(payload, dict):
            return payload
        return {"raw": payload}

    def execution_tail(self, limit: int = 50) -> Dict[str, Any]:
        try:
            payload = self.get("/debug/execution_tail", default={}, limit=limit)
        except HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return {"path": None, "lines": []}
            raise
        if isinstance(payload, dict):
            lines = payload.get("lines")
            if isinstance(lines, list):
                payload["lines"] = [str(line) for line in lines]
            return payload
        return {"path": None, "lines": []}

    def logs_archive(self) -> bytes:
        response = self._request("GET", "/diagnostics/logs/export", timeout=15)
        return bytes(response.content or b"")

    def strategy_config(self) -> Any:
        return self.get("/strategy/config", default={})

    def strategy_update(self, payload: Dict[str, Any]) -> Any:
        return self.post("/strategy/config", json=payload)

    def risk_config(self) -> Any:
        return self.get("/risk/config", default={})

    def risk_update(self, payload: Dict[str, Any]) -> Any:
        return self.post("/risk/config", json=payload)

    def risk_reset_kill_switch(self) -> Any:
        return self.post("/risk/killswitch/reset")

    def stream_status(self) -> Any:
        return self.get("/stream/status", default={})

    def stream_start(self) -> Any:
        return self.post("/stream/start")

    def stream_stop(self) -> Any:
        return self.post("/stream/stop")

    def cancel_all_orders(self) -> Any:
        return self.post("/orders/cancel_all")

    def account(self) -> Any:
        return self._request_with_fallback("GET", ["/broker/account", "/alpaca/account"], default={})

    def positions(self) -> Any:
        try:
            return self.get("/broker/positions", default=[])
        except HTTPError as exc:
            if exc.response is not None and exc.response.status_code in {404, 405}:
                return self.get("/positions", default=[], live=True)
            raise

    def orders(self, *, status: Optional[str] = None, limit: Optional[int] = None) -> Any:
        params: Dict[str, Any] = {}
        if status is not None:
            params["status"] = status
        if limit is not None:
            params["limit"] = limit
        try:
            return self.get("/broker/orders", default=[], **params)
        except HTTPError as exc:
            if exc.response is not None and exc.response.status_code in {404, 405}:
                fallback_params = dict(params) if params else {"live": True}
                return self.get("/orders", default=[], **fallback_params)
            raise

    def pnl_summary(self) -> Any:
        return self.get("/pnl/summary", default={})

    def telemetry_metrics(self) -> Any:
        return self.get("/telemetry/metrics", default={})

    def telemetry_trades(self) -> Any:
        return self.get("/telemetry/trades", default=[])

    def exposure(self) -> Any:
        return self.get("/telemetry/exposure", default={})

    def _request_with_fallback(
        self,
        method: str,
        paths: Sequence[str],
        *,
        default: Any = None,
        **kwargs: Any,
    ) -> Any:
        last_exc: Optional[Exception] = None
        for candidate in paths:
            try:
                if method.upper() == "GET":
                    return self.get(candidate, default=default, **kwargs)
                return self.post(candidate, **kwargs)
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
        if default is not None:
            return default
        raise RuntimeError("No request paths provided")


def get_client() -> ApiClient:
    return ApiClient()


def json_get(path: str, **kwargs: Any) -> Dict[str, Any]:
    result = get_client().get(path, **kwargs)
    return result if isinstance(result, dict) else {"data": result}


def json_post(path: str, payload: Any, **kwargs: Any) -> Dict[str, Any]:
    result = get_client().post(path, json=payload, **kwargs)
    return result if isinstance(result, dict) else {"data": result}


def _base_url() -> str:
    override = _session_override()
    if override:
        sanitized = _sanitize_base(override)
        if sanitized:
            return sanitized
    return discover_base_url()


def build_url(path: str) -> str:
    return urljoin(_base_url().rstrip("/") + "/", path.lstrip("/"))


__all__ = [
    "ApiClient",
    "get_client",
    "json_get",
    "json_post",
    "discover_base_url",
    "reset_discovery_cache",
    "build_url",
]
