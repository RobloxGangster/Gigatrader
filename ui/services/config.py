"""Configuration helpers for UI services."""

from __future__ import annotations

import os

from ui.lib.api_client import discover_base_url, reset_discovery_cache


def api_base_url() -> str:
    """
    API base URL used by the UI. Prefer explicit env override,
    otherwise use the discovered base (cached).
    """

    return os.environ.get("API_BASE_URL") or discover_base_url()


def force_redetect_api_base() -> str:
    """For diagnostics: clear cache and rediscover."""

    reset_discovery_cache()
    return api_base_url()


def mock_mode() -> bool:
    """Return whether the UI should run in mock mode."""

    return os.environ.get("MOCK_MODE", "true").lower() == "true"
