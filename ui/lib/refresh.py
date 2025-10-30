"""Safe refresh helpers for Streamlit pages."""

from __future__ import annotations

import time

import streamlit as st


def safe_autorefresh(interval_ms: int, key: str) -> None:
    """Polyfill for ``st.autorefresh`` that degrades gracefully."""

    if hasattr(st, "autorefresh"):
        st.autorefresh(interval=interval_ms, key=key)  # type: ignore[attr-defined]
        return
    st.session_state.setdefault("__next_refresh_at__", time.time() + interval_ms / 1000.0)


def should_rerender_from_polyfill() -> bool:
    """Return True if the polyfill indicates the page should rerender."""

    nxt = st.session_state.get("__next_refresh_at__")
    if not nxt:
        return False
    if time.time() >= nxt:
        st.session_state.pop("__next_refresh_at__", None)
        return True
    return False


__all__ = ["safe_autorefresh", "should_rerender_from_polyfill"]
