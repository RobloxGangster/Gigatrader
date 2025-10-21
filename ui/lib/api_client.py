"""Resilient HTTP client with backend auto-discovery and fallbacks."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

_DEFAULT_BASES = [
    os.getenv("API_BASE_URL") or "",
    os.getenv("GIGAT_API_URL") or "",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]
_DEFAULT_PREFIXES = ["", "/api", "/v1"]


def _norm(value: str | None) -> str:
    """Return a normalised base string without trailing slashes."""

    return re.sub(r"/+$", "", str(value or "").strip())


class ApiClient:
    """HTTP client that discovers the backend base URL and retries on failures."""

    def __init__(
        self,
        base: Optional[str] = None,
        bases: Optional[List[str]] = None,
        timeout: float = 10.0,
    ) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.trust_env = False

        self._bases = self._build_base_candidates(base=base, bases=bases)
        self._discovered: Optional[Tuple[str, str]] = None
        self._last_err: Optional[str] = None
        self._reachable = False

    # ------------------------------------------------------------------
    # Base discovery helpers
    # ------------------------------------------------------------------
    def _build_base_candidates(
        self, *, base: Optional[str], bases: Optional[List[str]]
    ) -> List[str]:
        candidates: List[str] = []

        # 1) Streamlit secrets (highest precedence)
        try:  # pragma: no cover - optional runtime dependency
            import streamlit as st  # type: ignore

            secret_base = st.secrets.get("api", {}).get("base_url")  # type: ignore[attr-defined]
            if secret_base:
                candidates.append(str(secret_base))
        except Exception:
            pass

        # 2) Explicitly supplied bases / base argument
        if bases:
            candidates.extend(bases)
        if base:
            candidates.append(base)

        # 3) Environment variables
        for env_key in ("API_BASE_URL", "GIGAT_API_URL"):
            env_value = os.getenv(env_key)
            if env_value:
                candidates.append(env_value)

        # 4) Defaults
        candidates.extend(_DEFAULT_BASES)

        deduped: List[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            normalised = _norm(candidate)
            if not normalised or normalised in seen:
                continue
            seen.add(normalised)
            deduped.append(normalised)

        if not deduped:
            deduped.append(_norm("http://127.0.0.1:8000"))
        return deduped

    def base(self) -> str:
        """Return the resolved base URL, including prefix if known."""

        resolved = self.base_url
        return resolved.rstrip("/") if resolved else resolved

    @property
    def base_url(self) -> str:
        self._ensure_discovered()
        if self._discovered:
            base, prefix = self._discovered
            return f"{base}{prefix}" if prefix else base
        return self._bases[0]

    @property
    def default_base_url(self) -> str:
        return self._bases[0]

    def explain_last_error(self) -> Optional[str]:
        return self._last_err

    def is_reachable(self) -> bool:
        self._ensure_discovered()
        return self._reachable

    def _first_ok(self, path: str) -> Optional[Tuple[str, str, requests.Response]]:
        errors: List[str] = []
        for base in self._bases:
            for prefix in _DEFAULT_PREFIXES:
                url = f"{base}{prefix}{path}"
                try:
                    response = self.session.get(url, timeout=self.timeout)
                except Exception as exc:  # noqa: BLE001 - defensive guard
                    errors.append(f"{url}: {type(exc).__name__}: {exc}")
                    continue
                if response.ok:
                    self._reachable = True
                    return (_norm(base), _norm(prefix), response)
                errors.append(f"{url}: HTTP {response.status_code}")
        if errors:
            self._last_err = errors[-1]
        return None

    def _ensure_discovered(self) -> None:
        if self._discovered is not None:
            return
        probe = self._first_ok("/health")
        if probe:
            base, prefix, _ = probe
            self._discovered = (base, prefix)
            self._last_err = None
            return
        self._reachable = False
        if self._bases:
            self._discovered = (_norm(self._bases[0]), "")
        if not self._last_err:
            self._last_err = "No healthy backend discovered"

    # ------------------------------------------------------------------
    # Core HTTP helpers
    # ------------------------------------------------------------------
    def request(self, method: str, path: str, **kwargs) -> requests.Response:
        if not path.startswith("/"):
            path = "/" + path.lstrip("/")

        self._ensure_discovered()
        base, prefix = self._discovered or (_norm(self._bases[0]), "")
        url = f"{base}{prefix}{path}"

        timeout = kwargs.pop("timeout", self.timeout)
        try:
            response = self.session.request(method, url, timeout=timeout, **kwargs)
        except Exception as exc:  # noqa: BLE001 - propagate with context
            self._last_err = f"{url}: {type(exc).__name__}: {exc}"
            raise

        if response.status_code == 404:
            alternate = self._first_ok(path)
            if alternate:
                base2, prefix2, response2 = alternate
                self._discovered = (base2, prefix2)
                self._reachable = True
                self._last_err = None
                return response2

        try:
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001 - surface HTTP errors
            self._last_err = f"{url}: {type(exc).__name__}: {exc}"
            raise

        self._reachable = True
        self._last_err = None
        return response

    def _decode(self, response: requests.Response) -> Any:
        content_type = response.headers.get("content-type", "")
        if "json" in content_type:
            try:
                return response.json()
            except ValueError:
                return json.loads(response.text or "{}")
        return response.content

    def _request(self, method: str, path: str, **kwargs) -> Any:
        response = self.request(method, path, **kwargs)
        payload = self._decode(response)
        return payload

    def get(self, path: str, **kwargs) -> Any:
        return self._request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> Any:
        return self._request("POST", path, **kwargs)

    def get_json(self, path: str, **kwargs) -> Dict[str, Any]:
        response = self.request("GET", path, **kwargs)
        payload = self._decode(response)
        if isinstance(payload, (bytes, bytearray)):
            try:
                return json.loads(payload.decode("utf-8"))
            except Exception:
                return {}
        if isinstance(payload, str):
            try:
                return json.loads(payload)
            except Exception:
                return {}
        if isinstance(payload, dict):
            return payload
        return {}

    # ------------------------------------------------------------------
    # Convenience endpoints
    # ------------------------------------------------------------------
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

    def orchestrator_start(
        self, preset: Optional[str] = None, mode: Optional[str] = None
    ) -> Dict[str, Any]:
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
    try:
        base = client.base()
    except Exception:
        base = client.default_base_url
    _DISCOVERY_CACHE = base.rstrip("/")
    return _DISCOVERY_CACHE


def reset_discovery_cache() -> None:
    """Reset the cached discovery result (primarily for tests)."""

    global _DISCOVERY_CACHE
    _DISCOVERY_CACHE = None
