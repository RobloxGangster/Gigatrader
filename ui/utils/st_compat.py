"""Streamlit compatibility helpers."""

from __future__ import annotations

import streamlit as st


def safe_rerun() -> None:
    """Trigger a Streamlit rerun across supported versions."""

    st.rerun()
