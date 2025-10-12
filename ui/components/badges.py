"""Reusable badge components."""

from __future__ import annotations

import streamlit as st


PROFILE_BADGES = {
    "paper": ("🧪 Paper", "green"),
    "live": ("⚠️ Live", "red"),
}


def profile_badge(profile: str, live_enabled: bool) -> None:
    """Render the current profile badge in the sidebar."""
    label, color = PROFILE_BADGES.get(profile, (profile.title(), "gray"))
    disabled = profile == "live" and not live_enabled
    st.sidebar.markdown(
        f"<div style='padding:4px 8px;border-radius:6px;background-color:{color};color:white;font-weight:600;'>"
        f"{label}{' (disabled)' if disabled else ''}</div>",
        unsafe_allow_html=True,
    )


def status_pill(label: str, value: str, *, variant: str = "neutral") -> None:
    colors = {
        "positive": "#38A169",
        "negative": "#E53E3E",
        "neutral": "#4A5568",
        "warning": "#DD6B20",
    }
    st.markdown(
        f"<span style='display:inline-flex;align-items:center;padding:2px 8px;border-radius:12px;"
        f"background:{colors.get(variant, colors['neutral'])};color:white;font-size:0.75rem;'>"
        f"<strong style='margin-right:6px;'>{label}:</strong>{value}</span>",
        unsafe_allow_html=True,
    )
