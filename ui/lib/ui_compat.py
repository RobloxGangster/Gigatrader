from __future__ import annotations

import typing as _t

import streamlit as st


def _get_attr(name: str) -> _t.Optional[_t.Callable[..., _t.Any]]:
    """Fetch a Streamlit attribute if it exists, else None."""

    return getattr(st, name, None)


def safe_rerun() -> None:
    """Call st.rerun when available; fall back to experimental_rerun if needed."""

    fn = _get_attr("rerun") or _get_attr("experimental_rerun")
    if fn:
        fn()
    # else: silent no-op (best-effort compatibility)


def auto_refresh(interval_ms: int, key: str) -> None:
    """
    Compatibility wrapper for st.autorefresh.
    - Uses st.autorefresh when present (modern Streamlit).
    - Otherwise, no-ops so pages don’t crash in environments without it.
    """

    fn = _get_attr("autorefresh")
    if fn:
        # type: ignore[func-returns-value]
        fn(interval=interval_ms, key=key)
    # else: silent no-op


__all__ = ["safe_rerun", "auto_refresh"]

