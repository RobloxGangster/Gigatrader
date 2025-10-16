"""Signals preview page."""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ui.services.backend import BrokerAPI
from ui.state import AppSessionState
from ui.utils.format import fmt_pct
from ui.utils.num import to_float

DEFAULT_UNIVERSE = ["SPY", "AAPL", "MSFT", "NVDA"]


def _render_chart(bars: List[Dict[str, Any]]) -> None:
    if not bars:
        st.info("No bar data available for preview.")
        return
    df = pd.DataFrame(bars)
    df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values("time")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna()
    if df.empty:
        st.info("No valid bar data to chart.")
        return

    df["ema12"] = df["close"].ewm(span=12, adjust=False).mean()
    df["ema26"] = df["close"].ewm(span=26, adjust=False).mean()
    df["vwap"] = (df["close"] * df["volume"]).cumsum() / df["volume"].cumsum()

    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=df["time"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="Price",
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
        )
    )
    fig.add_trace(go.Scatter(x=df["time"], y=df["ema12"], mode="lines", name="EMA 12", line=dict(color="#42a5f5")))
    fig.add_trace(go.Scatter(x=df["time"], y=df["ema26"], mode="lines", name="EMA 26", line=dict(color="#1e88e5")))
    fig.add_trace(go.Scatter(x=df["time"], y=df["vwap"], mode="lines", name="VWAP", line=dict(color="#fdd835")))
    fig.update_layout(margin=dict(l=0, r=0, t=24, b=0), height=360)
    st.plotly_chart(fig, use_container_width=True)


def _flatten_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    row = {
        "kind": candidate.get("kind"),
        "symbol": candidate.get("symbol"),
        "side": candidate.get("side"),
        "entry": to_float(candidate.get("entry")),
        "stop": to_float(candidate.get("stop")),
        "target": to_float(candidate.get("target")),
        "confidence": to_float(candidate.get("confidence")),
        "rationale": candidate.get("rationale"),
        "strategy": (candidate.get("meta") or {}).get("strategy"),
    }
    return row


def render(api: BrokerAPI, state: AppSessionState) -> None:
    st.title("Signal Preview")

    st.caption("Inspect the latest signals from the strategy engine and enrich them with ML probabilities.")

    universe = st.multiselect("Universe", DEFAULT_UNIVERSE, default=DEFAULT_UNIVERSE)
    profile = st.selectbox("Profile", ["balanced", "aggressive", "conservative"], index=0)
    refresh = st.button("Preview Signals")

    if refresh:
        try:
            data = api.preview_signals(profile=profile, universe=universe)
        except Exception as exc:  # pragma: no cover - UI safeguard
            st.error(f"Failed to load signals: {exc}")
            data = {"error": str(exc)}
        st.session_state["signal_preview"] = data
        st.session_state["signal_profile"] = profile

    payload = st.session_state.get("signal_preview")
    if not payload:
        st.info("Use the controls above to preview the current signal candidates.")
        return

    if payload.get("error"):
        st.warning(payload["error"])
        return

    candidates = payload.get("candidates", [])
    if not candidates:
        st.info("No signals available for the current configuration.")
        return

    try:
        status = api.get_ml_status()
    except Exception:
        status = {"status": "missing"}

    predictions: Dict[tuple[str, str], float] = {}
    if status.get("model"):
        for candidate in candidates:
            if candidate.get("kind") != "equity":
                continue
            key = (candidate.get("symbol"), candidate.get("side"))
            try:
                resp = api.ml_predict(candidate.get("symbol", ""))
            except Exception:
                continue
            proba = resp.get("p_up_15m")
            if isinstance(proba, (int, float)):
                predictions[key] = float(proba)

    rows = []
    for candidate in candidates:
        row = _flatten_candidate(candidate)
        key = (row["symbol"], row["side"])
        if key in predictions:
            row["p_up_15m"] = predictions[key]
        rows.append(row)

    df = pd.DataFrame(rows)
    if "p_up_15m" in df.columns:
        df["p_up_15m"] = df["p_up_15m"].apply(lambda v: fmt_pct(v) if isinstance(v, (int, float)) else v)
    st.dataframe(df, use_container_width=True)

    equity_candidates = [cand for cand in candidates if cand.get("kind") == "equity"]
    if not equity_candidates:
        return

    options = [
        f"{cand.get('symbol')} ({cand.get('side')}) – {cand.get('meta', {}).get('strategy', 'unknown')}"
        for cand in equity_candidates
    ]
    selection = st.selectbox("Select signal", options, index=0)
    selected = equity_candidates[options.index(selection)]

    col1, col2, col3 = st.columns(3)
    col1.metric("Entry", f"{to_float(selected.get('entry')):.2f}")
    if selected.get("stop"):
        col2.metric("Stop", f"{to_float(selected.get('stop')):.2f}")
    if selected.get("target"):
        col3.metric("Target", f"{to_float(selected.get('target')):.2f}")

    st.write(selected.get("rationale"))
    preview_bars = (selected.get("meta") or {}).get("preview_bars", [])
    _render_chart(preview_bars)
