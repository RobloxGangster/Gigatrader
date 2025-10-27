from __future__ import annotations

import os
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests


def _truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on", "y"}:
        return True
    if text in {"0", "false", "no", "off", "n"}:
        return False
    return default


@dataclass
class RuntimeFlags:
    mock_mode: bool
    dry_run: bool
    broker: str
    profile: str
    paper_trading: bool
    market_data_source: str
    base_url: str
    backend: Dict[str, Any]


def _derive_base_url(api) -> str:
    base = getattr(api, "base_url", None) or os.getenv("BACKEND_BASE_URL") or "http://127.0.0.1:8000"
    return str(base).rstrip("/")


def _probe_json(url: str) -> Optional[dict]:
    try:
        response = requests.get(url, timeout=2)
    except Exception:
        return None
    if not response.ok:
        return None
    if not response.headers.get("content-type", "").startswith("application/json"):
        return None
    try:
        return response.json()
    except ValueError:
        return None


def _fetch_backend_flags(base_url: str) -> Dict[str, Any]:
    payload = _probe_json(f"{base_url}/debug/runtime")
    if isinstance(payload, dict):
        return payload
    health = _probe_json(f"{base_url}/health")
    if isinstance(health, dict):
        return {
            "mock_mode": health.get("mock_mode", health.get("mock")),
            "dry_run": health.get("dry_run"),
            "broker": health.get("broker"),
            "profile": health.get("profile"),
            "paper_trading": health.get("paper_mode"),
            "market_data_source": health.get("stream"),
        }
    return {}


def get_runtime_flags(api) -> RuntimeFlags:
    base_url = _derive_base_url(api)
    backend_flags = _fetch_backend_flags(base_url)

    mock_mode = _truthy(backend_flags.get("mock_mode"))
    dry_run = _truthy(backend_flags.get("dry_run"))
    broker = str(backend_flags.get("broker") or "alpaca")
    profile = str(backend_flags.get("profile") or "paper")
    paper_trading = _truthy(backend_flags.get("paper_trading"), default=profile.lower() != "live")
    market_source_raw = backend_flags.get("market_data_source") or backend_flags.get("stream")
    market_data_source = str(market_source_raw or ("mock" if mock_mode else "alpaca"))

    if not backend_flags:
        env_mock = _truthy(os.getenv("MOCK_MODE"))
        mock_mode = env_mock
        dry_run = _truthy(os.getenv("DRY_RUN"), default=False)
        broker = os.getenv("BROKER", "alpaca") or "alpaca"
        profile = os.getenv("PROFILE", "paper") or "paper"
        paper_trading = profile.strip().lower() != "live"
        market_data_source = "mock" if mock_mode else "alpaca"

    return RuntimeFlags(
        mock_mode=mock_mode,
        dry_run=dry_run,
        broker=broker,
        profile=profile,
        paper_trading=paper_trading,
        market_data_source=market_data_source,
        base_url=base_url,
        backend=dict(backend_flags),
    )
