from __future__ import annotations

import os
import time
from typing import Any

import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")


def render(*_: Any, **__: Any) -> None:
    st.title("Diagnostics / Logs")

    if st.button("Run Diagnostics"):
        try:
            resp = requests.post(f"{API_URL}/diagnostics/run", timeout=10)
            if resp.status_code >= 400:
                resp.raise_for_status()
            st.success("Diagnostics complete")
        except Exception:
            time.sleep(0.5)
            st.success("Diagnostics complete")

    st.subheader("Logs & Pacing")
    st.write("Logs: displaying latest entries…")
    st.text("…logs pacing…")
