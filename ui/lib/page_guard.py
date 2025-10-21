"""Shared helpers to ensure Streamlit pages degrade gracefully."""

from __future__ import annotations

import streamlit as st

from ui.lib.api_client import ApiClient


def require_backend(api: ApiClient) -> bool:
    """Render a banner if the backend is unreachable."""

    if not api.is_reachable():
        st.error(
            "Backend is not reachable. "
            "Start FastAPI on http://127.0.0.1:8000 or set [api].base_url in .streamlit/secrets.toml."
        )
        if api.explain_last_error():
            st.caption(f"Last error: {api.explain_last_error()}")
        return False
    return True
