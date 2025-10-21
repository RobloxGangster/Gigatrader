"""Centralized HTTP client with route discovery and fallback logic."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from typing import Any, Dict, Optional, Sequence, Tuple

DEFAULT_HOSTS = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]

PREFIXES: Sequence[str] = ("", "/api", "/v1")


def _get_env_base() -> Optional[str]:
    value = os.getenv("GIGAT_API_URL") or os.getenv("API_BASE_URL")
    if value:
        return value.rstrip("/")
    return None


def _try_request(url: str, method: str = "GET", data: bytes | None = None, timeout: float = 3.0) -> Tuple[int, Optional[str]]:
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            payload = resp.read().decode("utf-8", "ignore")
            return resp.getcode(), payload
    except urllib.error.HTTPError as exc:  # pragma: no cover - network branch
        try:
            body = exc.read().decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001 - defensive guard
            body = None
        return exc.code, body
    except Exception:  # noqa: BLE001 - defensive guard
        return -1, None


def _looks_ok(code: int) -> bool:
    return code in (200, 201, 202, 203, 204)


def _split_host_and_prefix(url: str) -> Tuple[str, int]:
    trimmed = url.rstrip("/")
    for idx, prefix in enumerate(PREFIXES):
        if prefix and trimmed.endswith(prefix):
            host = trimmed[: -len(prefix)] or ""
            return host.rstrip("/"), idx
    return trimmed, 0


@lru_cache(maxsize=1)
def discover_base_url() -> str:
    env = _get_env_base()
    if env:
        return env
    hosts = []
    for candidate in DEFAULT_HOSTS:
        if candidate and candidate.rstrip("/") not in hosts:
            hosts.append(candidate.rstrip("/"))

    for host in hosts:
        if not host:
            continue
        for prefix in PREFIXES:
            base = f"{host}{prefix}".rstrip("/")
            if not base:
                continue
            code, _ = _try_request(f"{base}/health")
            if _looks_ok(code):
                return base
            code, body = _try_request(f"{base}/openapi.json")
            if _looks_ok(code) and body:
                try:
                    spec = json.loads(body)
                    paths = spec.get("paths", {}) if isinstance(spec, dict) else {}
                    if any(str(path).startswith("/broker") for path in paths):
                        return base
                except Exception:  # noqa: BLE001 - defensive parse guard
                    continue
    return (env or DEFAULT_HOSTS[0]).rstrip("/")


def reset_discovery_cache() -> None:
    """Clear the cached discovery result (useful for tests)."""

    discover_base_url.cache_clear()


class ApiClient:
    """Minimal JSON-over-HTTP client with prefix fallback."""

    def __init__(self) -> None:
        base = discover_base_url().rstrip("/")
        host, prefix_index = _split_host_and_prefix(base)
        self._host = host.rstrip("/")
        self._prefix_index = prefix_index

    @property
    def base(self) -> str:
        prefix = PREFIXES[self._prefix_index]
        return f"{self._host}{prefix}" if prefix else self._host

    def _rotate_prefix(self) -> None:
        self._prefix_index = (self._prefix_index + 1) % len(PREFIXES)

    def _build_url(self, path: str, params: Dict[str, Any] | None = None) -> str:
        clean_path = "/" + path.lstrip("/")
        query = ""
        if params:
            query = "?" + urllib.parse.urlencode(params, doseq=True)
        prefix = PREFIXES[self._prefix_index]
        return f"{self._host}{prefix}{clean_path}{query}" if prefix else f"{self._host}{clean_path}{query}"

    def _json_request(
        self,
        method: str,
        path: str,
        *,
        params: Dict[str, Any] | None = None,
        payload: Dict[str, Any] | None = None,
    ) -> Any:
        data_bytes = None
        if payload is not None:
            data_bytes = json.dumps(payload).encode("utf-8")
        attempts = len(PREFIXES)
        for _ in range(attempts):
            url = self._build_url(path, params)
            code, body = _try_request(url, method=method, data=data_bytes)
            if _looks_ok(code):
                if body:
                    try:
                        return json.loads(body)
                    except Exception:  # noqa: BLE001 - defensive parse guard
                        return {}
                return {}
            if code == 404:
                self._rotate_prefix()
                continue
            raise RuntimeError(f"API request failed ({code}): {url}")
        raise RuntimeError(f"API request failed: {path} via base={self.base}")

    # --- Convenience wrappers used by Streamlit pages ---

    def health(self) -> Dict[str, Any]:
        return self._json_request("GET", "/health")

    def status(self) -> Dict[str, Any]:
        return self._json_request("GET", "/status")

    def account(self) -> Dict[str, Any]:
        return self._json_request("GET", "/broker/account")

    def positions(self) -> Any:
        return self._json_request("GET", "/broker/positions")

    def orders(self, status: str = "all", limit: int = 50) -> Any:
        return self._json_request(
            "GET",
            "/broker/orders",
            params={"status": status, "limit": limit},
        )

    def stream_status(self) -> Dict[str, Any]:
        return self._json_request("GET", "/stream/status")

    def orchestrator_status(self) -> Dict[str, Any]:
        return self._json_request("GET", "/orchestrator/status")

    def orchestrator_start(self, preset: str | None = None, mode: str | None = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if preset:
            payload["preset"] = preset
        if mode:
            payload["mode"] = mode
        return self._json_request("POST", "/orchestrator/start", payload=payload)

    def orchestrator_stop(self) -> Dict[str, Any]:
        return self._json_request("POST", "/orchestrator/stop")

    def orchestrator_reconcile(self) -> Dict[str, Any]:
        return self._json_request("POST", "/orchestrator/reconcile")

    def strategy_config(self) -> Dict[str, Any]:
        return self._json_request("GET", "/strategy/config")

    def strategy_update(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._json_request("POST", "/strategy/config", payload=payload)

    def risk_config(self) -> Dict[str, Any]:
        return self._json_request("GET", "/risk/config")

    def risk_update(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._json_request("POST", "/risk/config", payload=payload)

    def risk_reset_kill_switch(self) -> Dict[str, Any]:
        return self._json_request("POST", "/risk/killswitch/reset")

    def stream_start(self) -> Dict[str, Any]:
        return self._json_request("POST", "/stream/start")

    def stream_stop(self) -> Dict[str, Any]:
        return self._json_request("POST", "/stream/stop")

    def pnl_summary(self) -> Dict[str, Any]:
        return self._json_request("GET", "/pnl/summary")

    def exposure(self) -> Dict[str, Any]:
        return self._json_request("GET", "/telemetry/exposure")

    def recent_logs(self, limit: int = 200) -> Dict[str, Any]:
        return self._json_request("GET", "/logs/recent", params={"limit": limit})

    def cancel_all_orders(self) -> Dict[str, Any]:
        return self._json_request("POST", "/orders/cancel_all")

    def metrics_extended(self) -> Dict[str, Any]:
        return self._json_request("GET", "/metrics/extended")

    def paper_start(self, preset: str | None = None) -> Dict[str, Any]:
        payload = {"preset": preset} if preset else None
        return self._json_request("POST", "/paper/start", payload=payload or {})

    def paper_stop(self) -> Dict[str, Any]:
        return self._json_request("POST", "/paper/stop")

    def paper_flatten(self) -> Dict[str, Any]:
        return self._json_request("POST", "/paper/flatten")

    def live_start(self, preset: str | None = None) -> Dict[str, Any]:
        payload = {"preset": preset} if preset else None
        return self._json_request("POST", "/live/start", payload=payload or {})

    def diagnostics_run(self) -> Dict[str, Any]:
        return self._json_request("POST", "/diagnostics/run")
