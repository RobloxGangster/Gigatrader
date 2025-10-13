"""Option Chain & Greeks page."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from ui.services.backend import BrokerAPI
from ui.state import AppSessionState, update_session_state


def _chain_dataframe(
    api: BrokerAPI, symbol: str, expiry: str | None, liquidity_only: bool
) -> pd.DataFrame:
    chain = api.get_option_chain(symbol, expiry or None)
    rows = [row.model_dump() for row in chain.rows]
    df = pd.DataFrame(rows)
    if liquidity_only:
        df = df[df["is_liquid"]]
    return df


def _render_chain(df: pd.DataFrame, highlight_strategy: bool) -> None:
    if df.empty:
        st.warning("No option rows match filters.")
        return
    df = df.sort_values(by=["expiry", "strike", "option_type"]).reset_index(drop=True)
    target_idx = df["volume"].idxmax()
    if highlight_strategy:

        def highlight(row):
            color = "background-color: #2C5282; color: white;" if row.name == target_idx else ""
            return [color] * len(row)

        st.dataframe(df.style.apply(highlight, axis=1), use_container_width=True)
    else:
        st.dataframe(df, use_container_width=True)
    st.caption("Strategy pick highlights the highest volume contract in view.")


def _greeks_panel(api: BrokerAPI, symbol: str, expiry: str | None) -> None:
    default_contract = f"{symbol} {expiry or 'Next'} 150C"
    contract = st.text_input("Contract", value=default_contract)
    greeks = api.get_greeks(contract)
    try:
        st.json(json.loads(greeks.model_dump_json()))
    except Exception:
        st.json(greeks.model_dump(exclude_none=True, serialize_as_any=True))


def _spread_builder(df: pd.DataFrame) -> None:
    st.subheader("Spread Builder")
    if df.empty:
        st.info("Select a symbol/expiry to preview spreads.")
        return
    strikes = sorted(df["strike"].unique())
    col1, col2 = st.columns(2)
    long_strike = col1.selectbox("Long Strike", strikes, key="long_strike")
    short_strike = col2.selectbox(
        "Short Strike", strikes, index=min(1, len(strikes) - 1), key="short_strike"
    )
    long_mid = float(df[df["strike"] == long_strike]["mid"].iloc[0])
    short_mid = float(df[df["strike"] == short_strike]["mid"].iloc[0])
    debit = max(long_mid - short_mid, 0)
    notional = abs(long_strike - short_strike) * 100
    st.info(
        f"Debit spread preview → Net debit ${debit:.2f} / max risk ${debit * 100:.2f} / notional ${notional:.2f}"
    )


def render(api: BrokerAPI, state: AppSessionState) -> None:
    st.title("Option Chain & Greeks")
    symbol = st.selectbox(
        "Underlying",
        ["AAPL", "MSFT", "SPY"],
        index=["AAPL", "MSFT", "SPY"].index(state.selected_symbol),
    )
    expiry = st.text_input("Expiry (YYYY-MM-DD)", value=state.option_expiry or "")
    update_session_state(selected_symbol=symbol, option_expiry=expiry)

    liquidity_only = st.checkbox("Liquidity filter", value=True)
    min_oi = st.slider("Min Open Interest", min_value=0, max_value=2000, value=100, step=50)
    min_volume = st.slider("Min Volume", min_value=0, max_value=1000, value=50, step=25)
    highlight = st.toggle("Highlight strategy pick", value=True)

    df = _chain_dataframe(api, symbol, expiry or None, liquidity_only)
    if not df.empty:
        df = df[(df["oi"] >= min_oi) & (df["volume"] >= min_volume)]

    _render_chain(df, highlight)
    _greeks_panel(api, symbol, expiry or None)
    _spread_builder(df)
