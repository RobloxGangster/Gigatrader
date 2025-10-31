from __future__ import annotations

import typing as _t

import streamlit as st

from ui.lib.refresh import safe_autorefresh


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
    """Compatibility shim that delegates to :func:`safe_autorefresh`."""

    safe_autorefresh(interval_ms, key=key)


__all__ = ["safe_rerun", "auto_refresh"]

