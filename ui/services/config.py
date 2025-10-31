"""Configuration helpers for UI services."""

from __future__ import annotations

import os

import streamlit as st


def _sanitize(value: object | None) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned:
            return cleaned.rstrip("/") or cleaned
    return None


def api_base_url() -> str:
    """
    Return backend base URL without importing api_client to avoid circular imports.
    Priority: session_state.backend_base > BACKEND_BASE > GT_API_BASE_URL > default.
    """

    try:
        session_base = st.session_state.get("backend_base")  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - streamlit not initialised
        session_base = None
    for candidate in (
        session_base,
        os.getenv("BACKEND_BASE"),
        os.getenv("GT_API_BASE_URL"),
    ):
        cleaned = _sanitize(candidate)
        if cleaned:
            return cleaned
    return "http://127.0.0.1:8000"


def force_redetect_api_base() -> str:
    """For diagnostics: clear session cache and rediscover."""

    try:
        if "backend_base" in st.session_state:  # type: ignore[attr-defined]
            del st.session_state["backend_base"]  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - streamlit not initialised
        pass
    return api_base_url()


def mock_mode() -> bool:
    """Return whether the UI should run in mock mode."""

    return os.environ.get("MOCK_MODE", "true").lower() == "true"
