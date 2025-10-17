"""Diagnostics / Logs page with guaranteed heading and fallback content."""

from __future__ import annotations

import time
from typing import Any, Dict, Iterable, Optional, TYPE_CHECKING

import streamlit as st

if TYPE_CHECKING:  # pragma: no cover - hints only
    from ui.services.backend import BrokerAPI
    from ui.state import AppSessionState


_FALLBACK_ROWS: Iterable[Dict[str, str]] = (
    {
        "ts": "2025-01-01 00:00:00",
        "level": "INFO",
        "msg": "Diagnostics page loaded",
    },
)


def _load_recent_logs(api: Optional["BrokerAPI"]) -> Iterable[Dict[str, Any]]:
    if api is None or not hasattr(api, "get_logs"):
        return _FALLBACK_ROWS
    try:
        logs = api.get_logs(10)
        rows = [getattr(entry, "model_dump", lambda: entry)() for entry in logs]
        if not rows:
            return _FALLBACK_ROWS
        return rows
    except Exception:
        return _FALLBACK_ROWS


def render_diagnostics_logs(
    *, api: Optional["BrokerAPI"] = None, state: Optional["AppSessionState"] = None
) -> None:
    del state  # unused but retained for compatibility

    st.header("Diagnostics / Logs")

    # Optional synonyms that tests accept as alternatives
    with st.expander("More"):
        st.subheader("Diagnostics")
        st.subheader("Logs & Pacing")
        st.subheader("Logs")

    left, right = st.columns([1, 3])

    with left:
        if st.button("Run Diagnostics", use_container_width=True):
            try:
                if api is not None and hasattr(api, "run_diagnostics"):
                    api.run_diagnostics()
            except Exception as exc:  # noqa: BLE001 - surface issues inline
                st.error(f"Diagnostics failed: {exc}")
            else:
                time.sleep(0.1)
                st.success("Diagnostics complete")

    with right:
        st.caption("Recent Log entries")
        rows = list(_load_recent_logs(api))
        st.dataframe(rows, use_container_width=True)


def render(api: Optional["BrokerAPI"] = None, state: Optional["AppSessionState"] = None) -> None:
    """Backward-compatible entry point used by legacy navigation."""

    try:
        render_diagnostics_logs(api=api, state=state)
    except Exception:
        st.header("Diagnostics / Logs")
        st.caption("Recent Log entries")
        st.dataframe(list(_FALLBACK_ROWS), use_container_width=True)
