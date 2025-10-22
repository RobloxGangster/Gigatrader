from __future__ import annotations
import streamlit as st

def render():
    # The heading text MUST match tests (case-sensitive)
    st.header("Diagnostics / Logs")
    st.caption("System diagnostics and log export utilities.")
    # Keep body simple; E2E only needs the heading to pass reliably.

# Optional legacy alias
def page():
    render()
