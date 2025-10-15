from __future__ import annotations

import sys
import os
import pathlib
import re
from pathlib import Path

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

from ui.components import nav
from ui.services.backend import get_backend
from ui.services.config import api_base_url, mock_mode
from ui.utils.runtime import get_runtime_flags
from ui.state import AppSessionState, init_session_state


def _is_mock_mode() -> bool:
    return os.getenv("MOCK_MODE", "").strip().lower() in ("1", "true", "yes")

DEBUG_UI = os.getenv("UI_DEBUG", "").strip().lower() in ("1", "true", "yes")

def main() -> None:
    load_dotenv(override=False)
    st.set_page_config(page_title="Gigatrader Control Center", layout="wide")
    _hide_streamlit_sidebar_nav()

    st.sidebar.title("Gigatrader")

    # Always show the sidebar banner when MOCK_MODE is on
    if _is_mock_mode():
        st.sidebar.info("Mock mode is enabled")

    page_map = nav.build_page_map()
    if not page_map:
        st.error("No pages available. Check your UI modules.")
        return

    current_key = nav.render_sidebar(page_map, key="nav_current")  # dropdown in sidebar
    nav.render_quickbar(page_map, key="nav_current")

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

    # Detect mode and show a badge
    flags = get_runtime_flags(api)
    if flags.mock_mode:
        st.markdown(
            "<div style='padding:6px 10px;background:#ffdfe0;border:1px solid #ffb3b8;"
            "border-radius:8px;display:inline-block;font-weight:600;color:#8a1822'>"
            "🧪 MOCK MODE — broker calls are stubbed; no orders reach Alpaca paper."
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div style='padding:6px 10px;background:#e6fff3;border:1px solid #9de2bf;"
            "border-radius:8px;display:inline-block;font-weight:600;color:#0f5132'>"
            "✅ PAPER MODE — connected to Alpaca paper."
            "</div>",
            unsafe_allow_html=True,
        )
    st.write("")  # small spacer
    st.session_state["__mock_mode__"] = flags.mock_mode  # expose to pages

    if not _is_mock_mode() and mock_mode():
        st.sidebar.info("Mock mode enabled – using fixture backend.")
    st.sidebar.caption(f"API: {api_base_url()}")
    st.sidebar.caption(f"Profile: {state.profile}")

    default_entry = next(iter(page_map.values()))
    title, renderer = page_map.get(current_key, default_entry)
    renderer(api, state)  # type: ignore[misc]


if os.getenv("UI_DEBUG", "").lower() in ("1", "true", "yes"):
    root = pathlib.Path(__file__).resolve().parents[1]
    offenders = []
    patterns = [
        r"st\.sidebar\.radio\s*\(\s*[\"']Navigation",
        r"st\.sidebar\.selectbox\s*\(\s*[\"']Navigation",
        r"st\.sidebar\.page_link\s*\(",
        r"st\.sidebar\.(?:markdown|write)\s*\([^)]*(Control Center|Signals|Strategy Backtests|Backtest Reports|ML Ops|Option Chain|Diagnostics / Logs|Stream Status|Metrics \(Extended\)|ML Calibration)",
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
