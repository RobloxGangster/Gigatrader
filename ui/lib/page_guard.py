"""Shared helpers to ensure Streamlit pages degrade gracefully."""

from __future__ import annotations

import os

import streamlit as st

from ui.lib.api_client import ApiClient


def require_backend(api: ApiClient) -> bool:
    """Render a banner if the backend is unreachable."""

    mock_mode = bool(
        st.session_state.get("__mock_mode__")
        or os.getenv("MOCK_MODE", "").strip().lower() in {"1", "true", "yes"}
    )
    if mock_mode:
        return True

    if not api.is_reachable():
        st.error(
            "Backend is not reachable. "
            "Start FastAPI on http://127.0.0.1:8000 or set [api].base_url in .streamlit/secrets.toml."
        )
        err = api.explain_last_error()
        if err:
            st.caption(err)
        return False
    return True
