from __future__ import annotations

import os
import os

import requests
from dataclasses import dataclass
from typing import Optional


@dataclass
class RuntimeFlags:
    mock_mode: bool
    base_url: str


def _derive_base_url(api) -> str:
    # Try to get the base URL from the client; otherwise default to localhost.
    base = getattr(api, "base_url", None) or os.getenv("BACKEND_BASE_URL") or "http://127.0.0.1:8000"
    return str(base).rstrip("/")


def _probe_health(base_url: str) -> Optional[dict]:
    try:
        r = requests.get(f"{base_url}/health", timeout=2)
        if r.ok and r.headers.get("content-type", "").startswith("application/json"):
            return r.json()
    except Exception:
        pass
    return None


def get_runtime_flags(api) -> RuntimeFlags:
    # 1) UI process env has final say if explicitly set
    env_mock = os.getenv("MOCK_MODE")
    if env_mock is not None:
        mock_env = env_mock.strip().lower() in ("1", "true", "yes", "on")
    else:
        mock_env = False

    base_url = _derive_base_url(api)
    # 2) Ask backend /health for a hint, fall back to env
    health = _probe_health(base_url)
    mock_from_health = False
    if isinstance(health, dict):
        for k in ("mock_mode", "mock", "MOCK_MODE"):
            if k in health:
                v = str(health[k]).strip().lower()
                mock_from_health = v in ("1", "true", "yes", "on")
                break

    return RuntimeFlags(mock_mode=(mock_env or mock_from_health), base_url=base_url)
