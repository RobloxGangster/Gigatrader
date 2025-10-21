"""Resilient HTTP client with backend auto-discovery and fallbacks."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import requests

DEFAULT_BASES = ["http://127.0.0.1:8000", "http://localhost:8000"]
DEFAULT_PREFIXES = ["", "/api", "/v1"]
COMMON_FEATURE_PATHS = (
    "/broker/account",
    "/strategy/config",
    "/risk/config",
    "/pnl/summary",
    "/telemetry/exposure",
    "/stream/status",
    "/logs/recent",
)


def _split_base(candidate: str) -> Tuple[str, str]:
    """Return ``(host, prefix)`` for a candidate base URL."""

    value = str(candidate or "").strip()
    if not value:
        return "", ""
    trimmed = value.rstrip("/")
    for prefix in DEFAULT_PREFIXES[1:]:
        if trimmed.endswith(prefix):
            host = trimmed[: -len(prefix)] or ""
            return host.rstrip("/"), prefix
    return trimmed, ""


class ApiClient:
    """HTTP client that discovers the backend base URL and retries on failures."""

    def __init__(self, base: Optional[str] = None, timeout: float = 4.0):
        self.timeout = timeout
        self.session = requests.Session()
        # Avoid leaking proxy settings to localhost calls.
        self.session.trust_env = False
        self._discovered: Optional[Tuple[str, str]] = None
        self._last_err: Optional[str] = None

        bases: List[Tuple[str, str]] = []

        # 1) Streamlit secrets (best effort)
        try:
            import streamlit as st  # type: ignore

            base_from_secrets = st.secrets.get("api", {}).get("base_url")  # type: ignore[attr-defined]
            if base_from_secrets:
                bases.append(_split_base(base_from_secrets))
        except Exception:
            pass

        # 2) Environment variables
        for env_key in ("API_BASE_URL", "GIGAT_API_URL"):
            base_from_env = os.getenv(env_key)
            if base_from_env:
                bases.append(_split_base(base_from_env))

        # 3) Explicit argument
        if base:
            bases.append(_split_base(base))

        # 4) Fallback defaults
        bases.extend(_split_base(candidate) for candidate in DEFAULT_BASES)

        # Deduplicate while preserving order and drop empty hosts
        deduped: List[Tuple[str, str]] = []
        for host, prefix in bases:
            if not host:
                continue
            entry = (host.rstrip("/"), prefix.rstrip("/"))
            if entry not in deduped:
                deduped.append(entry)

        if not deduped:
            deduped.append(_split_base(DEFAULT_BASES[0]))

        self._candidates = deduped
        self._discover()

    # ---- Discovery helpers -------------------------------------------------

    @property
    def base_url(self) -> str:
        """Return the currently discovered base URL or the first candidate."""

        if self._discovered:
            host, prefix = self._discovered
            return f"{host}{prefix}" if prefix else host
        host, prefix = self._candidates[0]
        return f"{host}{prefix}" if prefix else host

    @property
    def default_base_url(self) -> str:
        host, prefix = self._candidates[0]
        return f"{host}{prefix}" if prefix else host

    def explain_last_error(self) -> Optional[str]:
        return self._last_err

    def is_reachable(self) -> bool:
        return self._discovered is not None

    def _discover(self) -> None:
        self._last_err = None
        last_error: Optional[str] = None

        for host, preferred_prefix in self._candidates:
            prefixes: List[str] = []
            if preferred_prefix in DEFAULT_PREFIXES:
                prefixes.append(preferred_prefix)
            for prefix in DEFAULT_PREFIXES:
                if prefix not in prefixes:
                    prefixes.append(prefix)

            for prefix in prefixes:
                url = f"{host}{prefix}/health" if prefix else f"{host}/health"
                try:
                    response = self.session.get(url, timeout=self.timeout)
                    if response.ok and "application/json" in response.headers.get("content-type", ""):
                        payload = response.json()
                        if isinstance(payload, dict) and payload.get("ok") is True:
                            self._discovered = (host, prefix.rstrip("/"))
                            self._last_err = None
                            return
                except Exception as exc:  # noqa: BLE001 - defensive network guard
                    last_error = f"{url}: {type(exc).__name__}: {exc}"
                    continue

        # OpenAPI-based discovery fallback
        for host, preferred_prefix in self._candidates:
            openapi_paths: List[str] = []
            if preferred_prefix:
                openapi_paths.append(f"{preferred_prefix}/openapi.json")
            for prefix in DEFAULT_PREFIXES:
                candidate = f"{prefix}/openapi.json" if prefix else "/openapi.json"
                if candidate not in openapi_paths:
                    openapi_paths.append(candidate)

            for path in openapi_paths:
                url = f"{host}{path}" if path.startswith("/") else f"{host}/{path}"
                try:
                    response = self.session.get(url, timeout=self.timeout)
                except Exception as exc:  # noqa: BLE001 - defensive network guard
                    last_error = f"{url}: {type(exc).__name__}: {exc}"
                    continue

                if not response.ok or "application/json" not in response.headers.get("content-type", ""):
                    last_error = f"{url}: HTTP {response.status_code}"
                    continue

                try:
                    spec = response.json()
                except Exception as exc:  # noqa: BLE001 - JSON parsing guard
                    last_error = f"{url}: {type(exc).__name__}: {exc}"
                    continue

                paths = spec.get("paths", {}) if isinstance(spec, dict) else {}
                prefix = self._infer_prefix_from_paths(paths)
                if prefix is not None:
                    self._discovered = (host, prefix.rstrip("/"))
                    self._last_err = None
                    return

        self._discovered = None
        if last_error:
            self._last_err = last_error
        elif not self._last_err:
            self._last_err = "No healthy backend discovered"

    def _infer_prefix_from_paths(self, paths: Dict[str, Any]) -> Optional[str]:
        if not isinstance(paths, dict):
            return None

        candidates: List[str] = []
        for full_path in paths.keys():
            if not isinstance(full_path, str):
                continue
            for feature_path in COMMON_FEATURE_PATHS:
                if full_path.endswith(feature_path):
                    prefix = full_path[: -len(feature_path)]
                    candidates.append(prefix)

        for preferred in ("", "/api", "/v1"):
            if preferred in candidates:
                return preferred

        return candidates[0] if candidates else None

    # ---- Core HTTP helpers -------------------------------------------------

    def get(self, path: str):
        return self._request("GET", path)

    def post(self, path: str, json: Optional[Dict[str, Any]] = None):
        return self._request("POST", path, json=json)

    def _request(self, method: str, path: str, **kwargs):
        if not path.startswith("/"):
            path = "/" + path.lstrip("/")

        if self._discovered is None:
            self._discover()
            if self._discovered is None:
                raise RuntimeError(f"Backend unreachable: {self._last_err}")

        base, prefix = self._discovered
        url = f"{base}{prefix}{path}" if prefix else f"{base}{path}"
        try:
            response = self.session.request(method, url, timeout=self.timeout, **kwargs)
            if response.status_code in (404, 405, 421, 307, 308):
                self._discover()
                if self._discovered is None:
                    raise RuntimeError(f"Backend lost: {self._last_err}")
                base, prefix = self._discovered
                url = f"{base}{prefix}{path}" if prefix else f"{base}{path}"
                response = self.session.request(method, url, timeout=self.timeout, **kwargs)

            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                return response.json()
            return response.content
        except Exception as exc:  # noqa: BLE001 - surface error details
            self._last_err = f"{url}: {type(exc).__name__}: {exc}"
            raise

    # ---- Convenience endpoints --------------------------------------------

    def health(self) -> Dict[str, Any]:
        data = self.get("/health")
        return data if isinstance(data, dict) else {"ok": True}

    def status(self) -> Dict[str, Any]:
        data = self.get("/status")
        return data if isinstance(data, dict) else {}

    def account(self) -> Dict[str, Any]:
        data = self.get("/broker/account")
        return data if isinstance(data, dict) else {}

    def positions(self):
        return self.get("/broker/positions")

    def orders(self, status: str = "all", limit: int = 50):
        return self.get(f"/broker/orders?status={status}&limit={int(limit)}")

    def stream_status(self) -> Dict[str, Any]:
        data = self.get("/stream/status")
        return data if isinstance(data, dict) else {}

    def orchestrator_status(self) -> Dict[str, Any]:
        data = self.get("/orchestrator/status")
        return data if isinstance(data, dict) else {}

    def orchestrator_start(self, preset: Optional[str] = None, mode: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if preset:
            payload["preset"] = preset
        if mode:
            payload["mode"] = mode
        data = self.post("/orchestrator/start", json=payload or {})
        return data if isinstance(data, dict) else {}

    def orchestrator_stop(self) -> Dict[str, Any]:
        data = self.post("/orchestrator/stop")
        return data if isinstance(data, dict) else {}

    def orchestrator_reconcile(self) -> Dict[str, Any]:
        data = self.post("/orchestrator/reconcile")
        return data if isinstance(data, dict) else {}

    def strategy_config(self) -> Dict[str, Any]:
        data = self.get("/strategy/config")
        return data if isinstance(data, dict) else {}

    def strategy_update(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = self.post("/strategy/config", json=payload)
        return data if isinstance(data, dict) else {}

    def risk_config(self) -> Dict[str, Any]:
        data = self.get("/risk/config")
        return data if isinstance(data, dict) else {}

    def risk_update(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = self.post("/risk/config", json=payload)
        return data if isinstance(data, dict) else {}

    def risk_reset_kill_switch(self) -> Dict[str, Any]:
        data = self.post("/risk/killswitch/reset")
        return data if isinstance(data, dict) else {}

    def stream_start(self) -> Dict[str, Any]:
        data = self.post("/stream/start")
        return data if isinstance(data, dict) else {}

    def stream_stop(self) -> Dict[str, Any]:
        data = self.post("/stream/stop")
        return data if isinstance(data, dict) else {}

    def pnl_summary(self) -> Dict[str, Any]:
        data = self.get("/pnl/summary")
        return data if isinstance(data, dict) else {}

    def exposure(self) -> Dict[str, Any]:
        data = self.get("/telemetry/exposure")
        return data if isinstance(data, dict) else {}

    def recent_logs(self, limit: int = 200) -> Dict[str, Any]:
        data = self.get(f"/logs/recent?limit={int(limit)}")
        return data if isinstance(data, dict) else {}

    def cancel_all_orders(self) -> Dict[str, Any]:
        data = self.post("/orders/cancel_all")
        return data if isinstance(data, dict) else {}

    def metrics_extended(self) -> Dict[str, Any]:
        data = self.get("/metrics/extended")
        return data if isinstance(data, dict) else {}

    def paper_start(self, preset: Optional[str] = None) -> Dict[str, Any]:
        payload = {"preset": preset} if preset else None
        data = self.post("/paper/start", json=payload or {})
        return data if isinstance(data, dict) else {}

    def paper_stop(self) -> Dict[str, Any]:
        data = self.post("/paper/stop")
        return data if isinstance(data, dict) else {}

    def paper_flatten(self) -> Dict[str, Any]:
        data = self.post("/paper/flatten")
        return data if isinstance(data, dict) else {}

    def live_start(self, preset: Optional[str] = None) -> Dict[str, Any]:
        payload = {"preset": preset} if preset else None
        data = self.post("/live/start", json=payload or {})
        return data if isinstance(data, dict) else {}

    def diagnostics_run(self) -> Dict[str, Any]:
        data = self.post("/diagnostics/run")
        return data if isinstance(data, dict) else {}

    def logs_download_bytes(self) -> bytes:
        raw = self._request("GET", "/logs/download")
        if isinstance(raw, bytes):
            return raw
        if isinstance(raw, str):
            return raw.encode("utf-8")
        return bytes(raw or b"")


_DISCOVERY_CACHE: Optional[str] = None


def discover_base_url() -> str:
    """Compatibility helper used by legacy config helpers."""

    global _DISCOVERY_CACHE
    if _DISCOVERY_CACHE is not None:
        return _DISCOVERY_CACHE

    for env_key in ("API_BASE_URL", "GIGAT_API_URL"):
        value = os.getenv(env_key)
        if value:
            _DISCOVERY_CACHE = str(value).rstrip("/")
            return _DISCOVERY_CACHE

    client = ApiClient()
    if client.is_reachable():
        _DISCOVERY_CACHE = client.base_url.rstrip("/")
    else:
        _DISCOVERY_CACHE = client.default_base_url.rstrip("/")
    return _DISCOVERY_CACHE


def reset_discovery_cache() -> None:
    """Reset the cached discovery result (primarily for tests)."""

    global _DISCOVERY_CACHE
    _DISCOVERY_CACHE = None
