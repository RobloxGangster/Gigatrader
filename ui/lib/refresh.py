"""Safe refresh helpers for Streamlit pages."""

from __future__ import annotations

import time
import streamlit as st


def safe_autorefresh(interval_ms: int = 5000, key: str = "auto") -> None:
    """Request a rerun roughly every ``interval_ms`` milliseconds."""

    if interval_ms <= 0:
        return

    try:
        from streamlit_autorefresh import st_autorefresh  # type: ignore

        st_autorefresh(interval=interval_ms, key=key)
        return
    except Exception:  # pragma: no cover - optional dependency
        pass

    rerun = getattr(st, "experimental_rerun", None) or getattr(st, "rerun", None)
    if rerun is None:
        return

    state_key = f"__safe_autorefresh_last__:{key}"
    now = time.time()
    last = float(st.session_state.get(state_key, 0.0) or 0.0)
    if (now - last) * 1000.0 >= float(interval_ms):
        st.session_state[state_key] = now
        rerun()


__all__ = ["safe_autorefresh"]
