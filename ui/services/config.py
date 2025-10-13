"""Configuration helpers for UI services."""

from __future__ import annotations

import os


def api_base_url() -> str:
    """Return the backend API base URL.

    Defaults to the local backend but allows overriding via environment
    variables. Trailing slashes are stripped so callers can safely join paths.
    """

    return os.environ.get("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def mock_mode() -> bool:
    """Return whether the UI should run in mock mode."""

    return os.environ.get("MOCK_MODE", "true").lower() == "true"
