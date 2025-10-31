"""Safe refresh helpers for Streamlit pages."""

from __future__ import annotations

import time
from typing import Optional

import streamlit as st


def safe_autorefresh(interval_ms: int, *, key: Optional[str] = None) -> None:
    """Request a rerender after ``interval_ms`` milliseconds when supported."""

    if interval_ms <= 0:
        return

    refresh_key = key or "default"

    if hasattr(st, "autorefresh"):
        kwargs = {"interval": interval_ms, "key": f"auto-{refresh_key}"}
        st.autorefresh(**kwargs)  # type: ignore[attr-defined]
        return

    rerun = getattr(st, "experimental_rerun", None) or getattr(st, "rerun", None)
    if rerun is None:
        return

    state_key = f"__safe_autorefresh_last__:{refresh_key}"
    now = time.time() * 1000
    last = float(st.session_state.get(state_key, 0.0) or 0.0)
    if now - last >= interval_ms:
        st.session_state[state_key] = now
        rerun()


__all__ = ["safe_autorefresh"]
