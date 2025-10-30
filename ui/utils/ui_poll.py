"""UI polling helpers for Streamlit rerun safety."""

from __future__ import annotations

import time

import streamlit as st


def debounced_poll(key: str, every_sec: float) -> bool:
    """Return True if the given poll should execute on this rerun."""

    now = time.time()
    next_key = f"{key}.next"
    next_at = float(st.session_state.get(next_key, 0.0) or 0.0)
    if now >= next_at:
        st.session_state[next_key] = now + float(every_sec)
        return True
    return False


__all__ = ["debounced_poll"]

