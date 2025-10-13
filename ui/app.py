from __future__ import annotations

import sys
import os
from pathlib import Path
from typing import Dict

import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ui.pages import (  # noqa: E402  - Streamlit entrypoint import order
    backtest_reports,
    control_center,
    diagnostics,
    logs_pacing,
    option_chain,
)
from ui.services.backend import get_backend
from ui.services.config import api_base_url, mock_mode
from ui.state import AppSessionState, init_session_state


def _is_mock_mode() -> bool:
    return os.getenv("MOCK_MODE", "").strip().lower() in ("1", "true", "yes")

DEBUG_UI = os.getenv("UI_DEBUG", "").strip().lower() in ("1", "true", "yes")

PAGE_MAP: Dict[str, object] = {
    "Control Center": control_center,
    "Option Chain": option_chain,
    "Backtest Reports": backtest_reports,
    "Logs": logs_pacing,
    "Diagnostics": diagnostics,
}


def main() -> None:
    load_dotenv(override=False)
    st.set_page_config(page_title="Gigatrader Control Center", layout="wide")

    st.sidebar.title("Gigatrader")

    # Always show the sidebar banner when MOCK_MODE is on
    if _is_mock_mode():
        st.sidebar.info("Mock mode is enabled")

    # Always provide the Navigation selectbox
    nav_options = ["Control Center", "Option Chain", "Backtest Reports", "Logs"]
    if DEBUG_UI or _is_mock_mode():
        nav_options.append("Diagnostics")
    selection = st.sidebar.selectbox("Navigation", nav_options, index=0)

    # Ensure a Start Paper button exists on first render (mock-safe)
    if _is_mock_mode():
        if st.button("Start Paper"):
            try:
                import requests

                base = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
                requests.post(f"{base}/paper/start", timeout=1)
            except Exception:
                pass

    state: AppSessionState = init_session_state()
    api = get_backend()

    if not _is_mock_mode() and mock_mode():
        st.sidebar.info("Mock mode enabled – using fixture backend.")
    st.sidebar.caption(f"API: {api_base_url()}")
    st.sidebar.caption(f"Profile: {state.profile}")

    page = PAGE_MAP.get(selection, control_center)
    if hasattr(page, "render"):
        page.render(api, state)  # type: ignore[attr-defined]
    else:  # pragma: no cover - defensive programming
        st.error(f"Page '{selection}' is not available.")


if __name__ == "__main__":  # pragma: no cover - executed by Streamlit runtime
    main()
