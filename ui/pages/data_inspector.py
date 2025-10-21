from __future__ import annotations

"""Data Inspector page."""


import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from ui.services.backend import BrokerAPI
from ui.state import AppSessionState

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


@st.cache_data(ttl=60)
def _load_bars(symbol: str) -> pd.DataFrame:
    path = _FIXTURES / f"bars_{symbol.lower()}.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def _render_ohlcv(df: pd.DataFrame) -> None:
    st.subheader("OHLCV Viewer")
    window = st.slider("Intraday window", 0, len(df) - 1, (0, min(len(df) - 1, 30)))
    subset = df.iloc[window[0] : window[1] + 1]
    st.dataframe(subset, use_container_width=True)


def _render_anomalies(df: pd.DataFrame) -> None:
    st.subheader("Anomalies")
    gaps = df[df["open"].diff().abs() > 0.8]
    stale = df[df["volume"] == 0]
    if gaps.empty and stale.empty:
        st.success("No gaps or stale bars detected in selection.")
    else:
        if not gaps.empty:
            st.warning("Price gaps detected:")
            st.dataframe(gaps[["timestamp", "open", "close"]])
        if not stale.empty:
            st.error("Stale bars (zero volume):")
            st.dataframe(stale[["timestamp", "volume"]])


def _render_timezone_trace(df: pd.DataFrame) -> None:
    st.subheader("Timezone Trace")
    eastern = ZoneInfo("America/New_York")
    sample = df.head(5).copy()
    sample["exchange_time"] = sample["timestamp"].dt.tz_localize("UTC").dt.tz_convert(eastern)
    st.dataframe(sample[["timestamp", "exchange_time"]])


def _render_cache_stats() -> None:
    hits = st.session_state.get("data_cache_hits", 0) + 1
    st.session_state["data_cache_hits"] = hits
    st.subheader("Cache Stats")
    st.json({"cache_hits": hits, "cache_misses": max(0, hits // 4 - 1)})


def render(api: BrokerAPI, state: AppSessionState) -> None:  # noqa: ARG001
    st.title("Data Inspector")
    df = _load_bars(state.selected_symbol)
    _render_ohlcv(df)
    _render_anomalies(df)
    _render_timezone_trace(df)
    _render_cache_stats()
