from __future__ import annotations

from typing import List

import pandas as pd
import requests
import streamlit as st

try:  # pragma: no cover - optional dependency guard
    import plotly.graph_objects as go  # type: ignore
except Exception:  # pragma: no cover - Plotly not available in minimal envs
    go = None  # type: ignore


def _parse_symbols(raw: str) -> List[str]:
    values = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if chunk:
            values.append(chunk)
    return values


def _build_reliability_chart(payload: dict):
    predicted = payload.get("bin_mean_predicted", [])
    observed = payload.get("bin_observed_frequency", [])
    if not predicted or not observed:
        return None

    x = [value if value is not None else None for value in predicted]
    y = [value if value is not None else None for value in observed]

    if go is None:
        return None

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=x,
            y=y,
            mode="lines+markers",
            name="Observed",
            line=dict(color="rgba(30, 136, 229, 0.9)"),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[0, 1],
            y=[0, 1],
            mode="lines",
            name="Perfect calibration",
            line=dict(color="rgba(120, 120, 120, 0.5)", dash="dash"),
            hoverinfo="skip",
        )
    )
    fig.update_layout(
        title="Reliability Curve",
        xaxis_title="Mean predicted probability",
        yaxis_title="Observed frequency",
        xaxis=dict(range=[0, 1]),
        yaxis=dict(range=[0, 1]),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=10, r=10, t=50, b=10),
        height=360,
    )
    return fig


def render(api_base: str = "http://127.0.0.1:8000") -> None:
    st.header("ML Calibration")
    st.caption("Visualise reliability for a registered production model.")

    model_name = st.text_input("Model name", value="toy_api")
    alias = st.text_input("Alias", value="production")
    col1, col2, col3 = st.columns([1.2, 1.2, 0.6])
    with col1:
        start = st.text_input("Start", value="2024-01-01T00:00:00Z")
    with col2:
        end = st.text_input("End", value="2024-01-02T00:00:00Z")
    with col3:
        bins = st.number_input("Bins", min_value=2, max_value=100, value=10, step=1)

    symbols_raw = st.text_input("Symbols (comma separated)", value="AAPL,MSFT")

    if st.button("Load calibration"):
        params: List[tuple[str, str]] = [
            ("model", model_name),
            ("alias", alias),
            ("start", start),
            ("end", end),
            ("bins", str(int(bins))),
        ]
        symbols = _parse_symbols(symbols_raw)
        if symbols:
            params.append(("symbols", ",".join(symbols)))

        try:
            with st.spinner("Fetching calibration data..."):
                response = requests.get(f"{api_base.rstrip('/')}/ml/calibration", params=params, timeout=10)
        except Exception as exc:  # pragma: no cover - UI safety
            st.error(f"Request failed: {exc}")
            return

        if response.status_code != 200:
            st.error(f"{response.status_code}: {response.text}")
            return

        payload = response.json()

        st.success("Calibration data loaded")
        st.metric("Brier score", f"{payload.get('brier_score', float('nan')):.4f}")

        chart = _build_reliability_chart(payload)
        if chart is not None:
            st.plotly_chart(chart, width="stretch")
        else:
            st.info("Plotly not available – showing tabular calibration details instead.")

        edges = payload.get("bin_edges", [])
        table = pd.DataFrame(
            {
                "bin_lower": edges[:-1] if len(edges) > 1 else [],
                "bin_upper": edges[1:] if len(edges) > 1 else [],
                "mean_predicted": payload.get("bin_mean_predicted", []),
                "observed_frequency": payload.get("bin_observed_frequency", []),
                "count": payload.get("bin_counts", []),
            }
        )
        if table.empty:
            st.info("No calibration bins available for the requested window.")
        else:
            st.dataframe(table, width="stretch")
