from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Dict

import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ui.pages import (  # noqa: E402  - Streamlit entrypoint import order
    backtest_reports,
    control_center,
    data_inspector,
    equity_risk,
    logs_pacing,
    option_chain,
    orders_positions,
    signals,
    trade_blotter,
)
from ui.services.backend import get_backend
from ui.services.config import api_base_url, mock_mode
from ui.state import AppSessionState, init_session_state


def _is_mock_mode() -> bool:
    return os.getenv("MOCK_MODE", "").strip().lower() in ("1", "true", "yes")

_PAGE_REGISTRY: Dict[str, object] = {
    "Control Center": control_center,
    "Orders & Positions": orders_positions,
    "Option Chain & Greeks": option_chain,
    "Equity & Risk": equity_risk,
    "Signals": signals,
    "Trade Blotter": trade_blotter,
    "Data Inspector": data_inspector,
    "Backtest Reports": backtest_reports,
    "Logs & Pacing": logs_pacing,
}

_NAVIGATION_MAP: Dict[str, str] = {
    "Control Center": "Control Center",
    "Option Chain": "Option Chain & Greeks",
    "Backtest Reports": "Backtest Reports",
    "Logs": "Logs & Pacing",
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
    nav_seed = set(nav_options)
    nav_options.extend([key for key in _PAGE_REGISTRY.keys() if key not in nav_seed])
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

    page_key = _NAVIGATION_MAP.get(selection, selection)
    page = _PAGE_REGISTRY.get(page_key, control_center)
    if hasattr(page, "render"):
        page.render(api, state)  # type: ignore[attr-defined]
    else:  # pragma: no cover - defensive programming
        st.error(f"Page '{selection}' is not available.")


if __name__ == "__main__":  # pragma: no cover - executed by Streamlit runtime
    main()
