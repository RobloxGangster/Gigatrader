"""Configuration helpers for UI services."""

from __future__ import annotations

import os

from ui.lib.api_client import discover_base_url, reset_discovery_cache


def api_base_url() -> str:
    """Return the discovered backend base URL."""

    return discover_base_url()


def reset_api_base_url_cache() -> None:
    """Clear the cached discovery base URL (testing helper)."""

    reset_discovery_cache()


def mock_mode() -> bool:
    """Return whether the UI should run in mock mode."""

    return os.environ.get("MOCK_MODE", "true").lower() == "true"
