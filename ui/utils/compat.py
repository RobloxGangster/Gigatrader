from __future__ import annotations

import streamlit as st
from typing import Any


def rerun() -> Any:
    """
    Streamlit rerun helper that no-ops on very old versions.
    """
    if hasattr(st, "rerun"):
        return st.rerun()
    # Last resort: do nothing rather than crash
    return None
