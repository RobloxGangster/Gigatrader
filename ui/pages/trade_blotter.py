"""Trade Blotter page."""

from __future__ import annotations

import json
from typing import Dict, List

import pandas as pd
import streamlit as st

from ui.components.tables import render_table
from ui.services.backend import BrokerAPI
from ui.state import AppSessionState, Trade


def _filters_form(state: AppSessionState) -> Dict[str, str]:
    with st.sidebar.expander("Trade Filters", expanded=True):
        with st.form("trade_filters"):
            date = st.text_input("Date", value=state.filters.get("timestamp", ""))
            symbol = st.text_input("Symbol", value=state.filters.get("symbol", ""))
            strategy = st.text_input("Strategy", value=state.filters.get("strategy", ""))
            outcome = st.selectbox("Outcome", ["", "win", "loss", "flat"], index=0)
            submitted = st.form_submit_button("Apply Filters")
        filters = {"timestamp": date, "symbol": symbol, "strategy": strategy, "outcome": outcome}
        if submitted:
            state.filters = filters
    return state.filters or filters


def _trade_metrics(trades: List[Trade]) -> None:
    if not trades:
        return
    df = pd.DataFrame([trade.model_dump() for trade in trades])
    total_pnl = df["pnl"].sum()
    wins = (df["outcome"] == "win").sum()
    win_rate = (wins / len(df)) * 100
    cols = st.columns(3)
    cols[0].metric("Trades", len(df))
    cols[1].metric("Total PnL", f"${total_pnl:,.2f}", delta_color="inverse")
    cols[2].metric("Win Rate", f"{win_rate:.1f}%")


def _trade_inspector(trades: List[Trade]) -> None:
    st.subheader("Inspect Trade")
    if not trades:
        st.info("No trades to inspect.")
        return
    selection = st.selectbox("Trade", [trade.trade_id for trade in trades], key="trade_select")
    trade: Trade = next(trade for trade in trades if trade.trade_id == selection)
    st.json(trade.model_dump(mode="json"))
    st.download_button(
        "Export trade JSON",
        json.dumps(trade.model_dump(mode="json"), indent=2),
        file_name=f"trade_{trade.trade_id}.json",
        mime="application/json",
        key="trade_download",
    )
    with st.expander("Signal Snapshot"):
        st.write(
            {
                "features": ["momentum", "volatility", "pacing"],
                "score": 0.78,
                "decision": "scale_in" if trade.side == "buy" else "reduce",
                "notes": "Derived from mock indicators for demonstration",
            }
        )


def render(api: BrokerAPI, state: AppSessionState) -> None:
    st.title("Trade Blotter")
    filters = _filters_form(state)
    trades = api.get_trades(filters)

    _trade_metrics(trades)
    render_table("trades", [trade.model_dump() for trade in trades])
    _trade_inspector(trades)
