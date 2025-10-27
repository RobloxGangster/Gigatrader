"""Shared helpers to ensure Streamlit pages degrade gracefully."""

from __future__ import annotations

import streamlit as st

from ui.lib.api_client import ApiClient
from ui.utils.runtime import get_runtime_flags


def require_backend(api: ApiClient) -> bool:
    """Render a banner if the backend is unreachable."""

    mock_state = st.session_state.get("__mock_mode__")
    if isinstance(mock_state, bool):
        mock_mode = mock_state
    else:
        try:
            flags = get_runtime_flags(api)
            mock_mode = bool(flags.mock_mode)
        except Exception:
            mock_mode = False
        st.session_state["__mock_mode__"] = mock_mode
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
