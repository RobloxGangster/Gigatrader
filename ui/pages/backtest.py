from __future__ import annotations

"""Interactive backtest runner page."""


from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from ui.lib.api_client import ApiClient
from ui.lib.page_guard import require_backend
from ui.services.backend import BrokerAPI
from ui.state import AppSessionState, update_session_state
from ui.utils.charts import render_equity_curve
from ui.utils.format import fmt_currency, fmt_pct
from ui.utils.num import to_float

STRATEGIES = [
    ("intraday_momo", "Intraday Momentum"),
    ("intraday_revert", "Intraday Mean Reversion"),
    ("swing_breakout", "Swing Breakout"),
]


def _display_stats(stats: Dict[str, Any]) -> None:
    cols = st.columns(4)
    cols[0].metric("CAGR", fmt_pct(stats.get("cagr", 0.0)))
    cols[1].metric("Sharpe", f"{to_float(stats.get('sharpe')):.2f}")
    cols[2].metric("Win Rate", fmt_pct(stats.get("winrate", 0.0)))
    cols[3].metric("Max DD", fmt_pct(stats.get("max_dd", 0.0)))
    cols = st.columns(3)
    cols[0].metric("Avg R", f"{to_float(stats.get('avg_r')):.2f}")
    cols[1].metric("Avg Trade", fmt_currency(stats.get("avg_trade", 0.0)))
    cols[2].metric("Return", fmt_pct(stats.get("return_pct", 0.0)))


def _render_trades(trades: List[Dict[str, Any]]) -> None:
    if not trades:
        st.info("No trades recorded for the run.")
        return
    df = pd.DataFrame(trades)
    st.dataframe(df, use_container_width=True)


def render(api: BrokerAPI, state: AppSessionState) -> None:
    st.title("Strategy Backtests")
    st.caption("Run deterministic backtests directly from the backend to sanity-check new ideas.")

    backend_guard = ApiClient()
    if not require_backend(backend_guard):
        st.stop()

    with st.form("backtest_form"):
        symbol = st.text_input("Symbol", value=state.selected_symbol)
        strategy_key = st.selectbox(
            "Strategy",
            options=[key for key, _ in STRATEGIES],
            format_func=lambda key: dict(STRATEGIES)[key],
        )
        days = st.slider("Lookback days", min_value=5, max_value=60, value=30)
        submitted = st.form_submit_button("Run Backtest")

    if submitted:
        try:
            result = api.run_strategy_backtest(symbol=symbol.upper(), strategy=strategy_key, days=days)
        except Exception as exc:  # pragma: no cover - UI safeguard
            st.error(f"Failed to run backtest: {exc}")
            return
        if result.get("error"):
            st.warning(result["error"])
            return
        st.session_state["backtest_result"] = result
        update_session_state(selected_symbol=symbol.upper())

    result = st.session_state.get("backtest_result")
    if not result:
        st.info("Run a backtest to see performance statistics and equity curves.")
        return

    stats = result.get("stats", {})
    _display_stats(stats)

    equity_curve = result.get("equity_curve", [])
    if equity_curve:
        st.subheader("Equity Curve")
        render_equity_curve(equity_curve)

    st.subheader("Trades")
    _render_trades(result.get("trades", []))
