from __future__ import annotations

import streamlit as st
from typing import Any


def rerun() -> Any:
    """
    Streamlit rerun that works across versions:
    - Prefer st.rerun() (new)
    - Fallback to st.experimental_rerun() (old)
    - No-op if neither exists (extremely old or exotic builds)
    """
    if hasattr(st, "rerun"):
        return st.rerun()
    if hasattr(st, "experimental_rerun"):
        return st.experimental_rerun()
    # Last resort: do nothing rather than crash
    return None
