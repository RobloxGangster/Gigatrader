from __future__ import annotations

import sys
import os
import pathlib
import re
from pathlib import Path
from typing import Dict

import streamlit as st


# Hide Streamlit's automatic multipage sidebar (and any stray nav blocks)
def _hide_streamlit_sidebar_nav() -> None:
    st.markdown(
        """
        <style>
        /* Hide the built-in 'Pages' navigator if present */
        section[data-testid="stSidebarNav"] { display: none !important; }
        /* Hide any sidebar ULs that look like nav lists */
        [data-testid="stSidebar"] ul,
        [data-testid="stSidebar"] nav { display: none !important; }
        /* If any page_link renders anchors, hide them */
        [data-testid="stSidebar"] a[href*="?"] { display: none !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ui.pages import (  # noqa: E402  - Streamlit entrypoint import order
    backtest,
    backtest_reports,
    control_center,
    diagnostics,
    logs_pacing,
    ml,
    option_chain,
    signals,
)
from ui.services.backend import get_backend
from ui.services.config import api_base_url, mock_mode
from ui.state import AppSessionState, init_session_state


def _is_mock_mode() -> bool:
    return os.getenv("MOCK_MODE", "").strip().lower() in ("1", "true", "yes")

DEBUG_UI = os.getenv("UI_DEBUG", "").strip().lower() in ("1", "true", "yes")

PAGE_MAP: Dict[str, object] = {
    "Control Center": control_center,
    "Signals": signals,
    "Strategy Backtests": backtest,
    "Backtest Reports": backtest_reports,
    "ML Ops": ml,
    "Option Chain": option_chain,
    "Logs": logs_pacing,
    "Diagnostics": diagnostics,
}


def main() -> None:
    load_dotenv(override=False)
    st.set_page_config(page_title="Gigatrader Control Center", layout="wide")
    _hide_streamlit_sidebar_nav()

    st.sidebar.title("Gigatrader")

    # Always show the sidebar banner when MOCK_MODE is on
    if _is_mock_mode():
        st.sidebar.info("Mock mode is enabled")

    # Always provide the Navigation selectbox
    nav_options = [
        "Control Center",
        "Signals",
        "Strategy Backtests",
        "Backtest Reports",
        "ML Ops",
        "Option Chain",
        "Logs",
    ]
    if DEBUG_UI or _is_mock_mode():
        nav_options.append("Diagnostics")
    page_map = {name: PAGE_MAP[name] for name in nav_options}
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

    page = page_map.get(selection, control_center)
    if hasattr(page, "render"):
        page.render(api, state)  # type: ignore[attr-defined]
    else:  # pragma: no cover - defensive programming
        st.error(f"Page '{selection}' is not available.")


if os.getenv("UI_DEBUG", "").lower() in ("1", "true", "yes"):
    root = pathlib.Path(__file__).resolve().parents[1]
    offenders = []
    patterns = [
        r"st\.sidebar\.radio\s*\(\s*[\"']Navigation",
        r"st\.sidebar\.selectbox\s*\(\s*[\"']Navigation",
        r"st\.sidebar\.page_link\s*\(",
        r"st\.sidebar\.(?:markdown|write)\s*\([^)]*(Control Center|Option Chain|Backtest Reports|Logs|Diagnostics)",
    ]
    rx = re.compile("|".join(patterns), re.IGNORECASE)
    for path in root.rglob("*.py"):
        if path.name == "app.py":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if rx.search(text):
            offenders.append(str(path))
    if offenders:
        print("[WARN] Duplicate sidebar nav found in:", offenders)


if __name__ == "__main__":  # pragma: no cover - executed by Streamlit runtime
    main()
