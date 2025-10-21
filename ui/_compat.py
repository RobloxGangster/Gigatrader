from __future__ import annotations

import streamlit as st


def safe_rerun() -> None:
    """Invoke the supported rerun helper across Streamlit versions."""

    if hasattr(st, "rerun"):
        st.rerun()  # type: ignore[call-arg]
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()  # type: ignore[attr-defined]
