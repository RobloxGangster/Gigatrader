"""Streamlit application entry point."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Callable, Dict

import streamlit as st

from ui.pages import (
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
from ui.services.backend import BrokerAPI, BackendError, get_backend
from ui.state import AppSessionState, init_session_state

PAGE_BUILDERS: Dict[str, Callable[[BrokerAPI, AppSessionState], None]] = {
    "Control Center": control_center.render,
    "Equity & Risk": equity_risk.render,
    "Trade Blotter": trade_blotter.render,
    "Orders & Positions": orders_positions.render,
    "Option Chain & Greeks": option_chain.render,
    "Signals & Strategy Params": signals.render,
    "Data Inspector": data_inspector.render,
    "Logs & Pacing": logs_pacing.render,
    "Backtest Reports": backtest_reports.render,
}


@lru_cache(maxsize=1)
def _live_enabled() -> bool:
    return os.getenv("LIVE_TRADING", "false").lower() == "true"


def _setup_page(state: AppSessionState) -> BrokerAPI:
    st.set_page_config(page_title="Gigatrader Control", layout="wide")
    api = get_backend()

    live_enabled = _live_enabled()
    profile = st.sidebar.radio("Profile", ["paper", "live"], index=0, disabled=not live_enabled)
    state.profile = profile

    from ui.components.badges import profile_badge

    profile_badge(profile, live_enabled)

    if os.getenv("MOCK_MODE", "true").lower() == "true":
        st.sidebar.warning("Mock mode", icon="🧪")

    st.sidebar.markdown("---")
    st.sidebar.caption("Keyboard: g+b Backtests, g+l Logs, . tail logs")
    return api


def _render_page(page: str, api: BrokerAPI, state: AppSessionState) -> None:
    try:
        PAGE_BUILDERS[page](api, state)
    except BackendError as exc:
        st.error(f"Backend request failed: {exc}")
        if st.button("Retry", key="retry_page"):
            st.experimental_rerun()


def main() -> None:
    state = init_session_state()
    api = _setup_page(state)

    st.sidebar.metric("Run ID", state.run_id or "—", help="Active paper run identifier")
    st.sidebar.caption("Trace ID: " + (state.last_trace_id or "n/a"))

    page = st.sidebar.selectbox("Navigation", list(PAGE_BUILDERS.keys()), key="page_selector")
    _render_page(page, api, state)


if __name__ == "__main__":
    main()

