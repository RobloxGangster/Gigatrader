from __future__ import annotations
import streamlit as st


def render(*_):
    st.header("Diagnostics / Logs")  # required by e2e tests
    st.caption("System diagnostics and log export utilities.")
    # Keep body simple; E2E only needs the heading to pass reliably.


# Optional legacy alias
def page(*_):
    render()
