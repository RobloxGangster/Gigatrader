"""Research insights page."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ui.services.backend import BrokerAPI
from ui.state import AppSessionState


def _fmt_decimal(value) -> str:
    try:
        return f"{float(value):.2f}"
    except Exception:
        return "—"


def render(api: BrokerAPI, state: AppSessionState) -> None:
    st.title("Research")
    st.caption("Explore indicator snapshots, historical trends, and profile-level research tools.")

    default_symbol = (state.selected_symbol or "SPY").upper()
    symbol = (
        st.text_input("Symbol", value=default_symbol, key="research_symbol")
        .strip()
        .upper()
        or default_symbol
    )
    lookback = st.slider("Lookback (days)", min_value=10, max_value=120, value=30, step=5)

    state.selected_symbol = symbol

    try:
        indicators = api.get_indicators(symbol, lookback)
    except Exception as exc:  # noqa: BLE001 - surface backend failures to the UI
        st.error(f"Failed to load indicators for {symbol}: {exc}")
        return

    st.subheader("Indicator Snapshot")
    c1, c2, c3 = st.columns(3)
    c1.metric("ATR", _fmt_decimal(indicators.atr))
    c2.metric("RSI", _fmt_decimal(indicators.rsi))
    c3.metric("Z-Score", _fmt_decimal(indicators.z_score))

    st.caption(f"Updated {indicators.updated_at.strftime('%Y-%m-%d %H:%M:%S')} UTC")

    if indicators.series:
        st.subheader("Series Breakdown")
        df = pd.DataFrame(
            {
                "Label": [series.label for series in indicators.series],
                "Value": [_fmt_decimal(series.value) for series in indicators.series],
                "Trend": [series.trend or "—" for series in indicators.series],
            }
        )
        st.dataframe(df, width="stretch")

        try:
            numeric = pd.Series([float(s.value) for s in indicators.series], name="value")
            chart_df = pd.DataFrame({"value": numeric})
            chart_df.index = [series.label for series in indicators.series]
            st.line_chart(chart_df, height=240)
        except Exception:
            pass
    else:
        st.info("No historical indicator series available for this symbol.")

    st.subheader("Notes")
    notes_key = "research_notes"
    default_notes = st.session_state.get(notes_key, "")
    st.text_area("Capture research notes", value=default_notes, key=notes_key, height=120)
