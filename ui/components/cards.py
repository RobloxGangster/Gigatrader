"""Reusable stat card components."""

from __future__ import annotations

from typing import Optional

import streamlit as st


def stat_card(
    title: str,
    value: str,
    *,
    delta: Optional[str] = None,
    help_text: Optional[str] = None,
    key: Optional[str] = None,
) -> None:
    """Render a KPI style card."""
    container = st.container()
    with container:
        st.markdown(
            f"<div style='border-radius:12px;border:1px solid #2D3748;padding:16px;background:#1A202C;'>"
            f"<div style='font-size:0.8rem;color:#A0AEC0;text-transform:uppercase;'>{title}</div>"
            f"<div style='font-size:1.6rem;font-weight:600;color:white;'>{value}</div>"
            f"<div style='font-size:0.75rem;color:#CBD5F5;'>{delta or ''}</div>"
            "</div>",
            unsafe_allow_html=True,
        )
        if help_text:
            st.caption(help_text)
