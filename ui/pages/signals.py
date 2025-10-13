"""Signals & Strategy Params page."""

from __future__ import annotations

import json
from typing import Dict

import pandas as pd
import streamlit as st

from ui.services.backend import BrokerAPI
from ui.state import AppSessionState, update_session_state


def _indicator_panel(api: BrokerAPI, symbol: str, lookback: int) -> Dict[str, float]:
    indicators = api.get_indicators(symbol, lookback)
    st.subheader("Real-time Indicators")
    cols = st.columns(4)
    cols[0].metric("ATR", indicators.atr)
    cols[1].metric("RSI", indicators.rsi)
    cols[2].metric("Z-Score", indicators.z_score)
    cols[3].metric("ORB", indicators.orb)
    st.caption(f"Last updated {indicators.updated_at}")

    if indicators.series:
        df = pd.DataFrame([series.model_dump() for series in indicators.series])
        st.dataframe(df, hide_index=True)
    return {
        "atr": float(indicators.atr),
        "rsi": float(indicators.rsi),
        "z_score": float(indicators.z_score),
        "orb": float(indicators.orb),
    }


def _strategy_form(api: BrokerAPI, state: AppSessionState) -> None:
    st.subheader("Strategy Parameters")
    defaults = state.strategy_params or {"atr_mult": 2.0, "risk_pct": 1.0, "size": 100}
    with st.form("params_form"):
        atr_mult = st.slider("ATR Multiplier", 1.0, 5.0, float(defaults.get("atr_mult", 2.0)))
        risk_pct = st.slider("Risk %", 0.5, 5.0, float(defaults.get("risk_pct", 1.0)))
        size = st.number_input("Position Size", value=int(defaults.get("size", 100)))
        submitted = st.form_submit_button("Apply to Paper Run")
        if submitted:
            params = {"atr_mult": atr_mult, "risk_pct": risk_pct, "size": size}
            api.apply_strategy_params(params)
            update_session_state(strategy_params=params)
            st.toast("Parameters pushed to paper run", icon="📡")


def _explainability_panel(indicator_snapshot: Dict[str, float], params: Dict[str, float]) -> None:
    st.subheader("Why this trade?")
    explanation = {
        "inputs": indicator_snapshot,
        "features": {
            "volatility": indicator_snapshot.get("atr", 0) * params.get("atr_mult", 2),
            "momentum_bias": indicator_snapshot.get("z_score", 0),
            "risk_budget": params.get("risk_pct", 1),
        },
        "decision": "enter-long" if indicator_snapshot.get("rsi", 50) < 60 else "neutral",
        "size": params.get("size", 100),
    }
    st.json(explanation)
    st.download_button(
        "Download explainability JSON",
        json.dumps(explanation, indent=2),
        file_name="why_this_trade.json",
        mime="application/json",
    )


def render(api: BrokerAPI, state: AppSessionState) -> None:
    st.title("Signals & Strategy Params")

    symbol = st.text_input("Symbol", value=state.selected_symbol)
    lookback = st.slider("Lookback", min_value=10, max_value=200, value=60, step=10)

    indicator_snapshot = _indicator_panel(api, symbol, lookback)
    _strategy_form(api, state)
    params = state.strategy_params or {"atr_mult": 2.0, "risk_pct": 1.0, "size": 100}
    _explainability_panel(indicator_snapshot, params)
