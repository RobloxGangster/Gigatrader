from __future__ import annotations

"""Research insights page."""


import pandas as pd
import streamlit as st

from ui.lib.api_client import ApiClient
from ui.lib.page_guard import require_backend
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

    backend_guard = ApiClient()
    if not require_backend(backend_guard):
        st.stop()

    default_symbol = state.selected_symbol or "SPY"
    symbol = (
        st.text_input("Symbol", value=default_symbol, key="research_symbol")
        .strip()
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
    if not indicators.has_data or not indicators.indicators:
        st.info("Indicators are not available yet. Waiting for bars…")
        return

    c1.metric("ATR", _fmt_decimal(indicators.latest("atr")))
    c2.metric("RSI", _fmt_decimal(indicators.latest("rsi")))
    zscore_value = indicators.latest("zscore") or indicators.latest("z_score")
    c3.metric("Z-Score", _fmt_decimal(zscore_value))

    last_ts = None
    for key in ("rsi", "atr", "zscore", "z_score"):
        series = indicators.indicators.get(key) or []
        for entry in reversed(series):
            if hasattr(entry, "timestamp") and getattr(entry, "timestamp"):
                last_ts = getattr(entry, "timestamp")
                break
            if isinstance(entry, dict) and entry.get("timestamp"):
                last_ts = pd.to_datetime(entry["timestamp"]).to_pydatetime()
                break
        if last_ts:
            break

    if last_ts:
        st.caption(f"Updated {last_ts.strftime('%Y-%m-%d %H:%M:%S')} UTC")

    df = indicators.frame()
    if df is not None and not df.empty:
        st.subheader("Indicator Series")
        st.dataframe(df, width="stretch")
        with pd.option_context("display.max_rows", None):
            try:
                st.line_chart(df, height=240)
            except Exception:
                pass
    else:
        st.info("No historical indicator series available for this symbol.")

    st.subheader("Notes")
    notes_key = "research_notes"
    default_notes = st.session_state.get(notes_key, "")
    st.text_area("Capture research notes", value=default_notes, key=notes_key, height=120)
