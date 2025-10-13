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
from ui.state import AppSessionState, init_session_state

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


def _render_sidebar(state: AppSessionState) -> str:
    api_base = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
    with st.sidebar:
        st.title("Gigatrader")
        if os.getenv("MOCK_MODE", "false").lower() == "true":
            st.info("Mock mode enabled – using fixture backend.")
        st.caption(f"API: {api_base}")
        st.caption(f"Profile: {state.profile}")
        selection = st.selectbox("Navigation", list(_PAGE_REGISTRY.keys()), index=0)
        return selection


def main() -> None:
    load_dotenv(override=False)
    st.set_page_config(page_title="Gigatrader Control Center", layout="wide")

    state = init_session_state()
    api = get_backend()
    selection = _render_sidebar(state)

    page = _PAGE_REGISTRY.get(selection, control_center)
    if hasattr(page, "render"):
        page.render(api, state)  # type: ignore[attr-defined]
    else:  # pragma: no cover - defensive programming
        st.error(f"Page '{selection}' is not available.")


if __name__ == "__main__":  # pragma: no cover - executed by Streamlit runtime
    main()
