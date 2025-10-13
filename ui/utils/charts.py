"""Chart helper utilities for the Gigatrader UI."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from decimal import Decimal
from typing import Any

import pandas as pd
import streamlit as st

from ui.state import EquityPoint

# Try to import Plotly lazily; keep module import safe
try:  # pragma: no cover - import-time guard
    import plotly.graph_objects as go  # type: ignore
except Exception:  # plotly not installed or import failed
    go = None  # type: ignore


ColorSpec = tuple[int, int, int]


def _rgba(color: ColorSpec, alpha: float = 1.0) -> str:
    return f"rgba({color[0]}, {color[1]}, {color[2]}, {alpha})"


def _points_to_dataframe(points: Sequence[EquityPoint] | Sequence[Any] | pd.DataFrame | pd.Series) -> pd.DataFrame:
    if isinstance(points, pd.DataFrame):
        df = points.copy()
    elif isinstance(points, pd.Series):
        df = pd.DataFrame({"equity": pd.to_numeric(points, errors="coerce")})
        df["timestamp"] = range(len(df))
    else:
        data = list(points)
        if not data:
            return pd.DataFrame()
        first = data[0]
        if hasattr(first, "model_dump"):
            df = pd.DataFrame(point.model_dump() for point in data)
        elif isinstance(first, EquityPoint):
            df = pd.DataFrame(
                {
                    "timestamp": point.timestamp,
                    "equity": point.equity,
                    "drawdown": getattr(point, "drawdown", None),
                    "exposure": getattr(point, "exposure", None),
                }
                for point in data
            )
        elif isinstance(first, dict):
            df = pd.DataFrame(data)
        else:
            df = pd.DataFrame({"equity": [float(value) for value in data]})
            df["timestamp"] = range(len(df))
    if "timestamp" in df.columns:
        try:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
        except Exception:
            if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
                df["timestamp"] = df["timestamp"].fillna(method="ffill").fillna(method="bfill")
    else:
        df["timestamp"] = range(len(df))
    for column in ("equity", "drawdown", "exposure"):
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    return df


def _format_equity_dataframe(equity_series: Sequence[float] | Sequence[EquityPoint] | pd.Series | pd.DataFrame) -> pd.DataFrame:
    df = _points_to_dataframe(equity_series)
    columns = ["timestamp", "equity"]
    if "drawdown" in df.columns:
        columns.append("drawdown")
    return df[columns]


def equity_curve_chart(
    equity_series: Sequence[float] | Sequence[EquityPoint] | pd.Series | pd.DataFrame,
    title: str = "Equity Curve",
):
    """
    Returns a Plotly Figure when Plotly is available; otherwise returns None.
    This function does NOT render to Streamlit by itself.
    """
    df = _format_equity_dataframe(equity_series)
    if go is None or df.empty:
        return None

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["equity"],
            mode="lines",
            name="Equity",
            line=dict(color=_rgba((56, 161, 105))),
        )
    )
    if "drawdown" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df["timestamp"],
                y=df["drawdown"],
                name="Drawdown",
                mode="lines",
                line=dict(color=_rgba((229, 62, 62))),
                fill="tozeroy",
                fillcolor=_rgba((229, 62, 62), 0.1),
            )
        )
    fig.update_layout(
        title=title,
        xaxis_title="Timestamp" if pd.api.types.is_datetime64_any_dtype(df["timestamp"]) else "Step",
        yaxis_title="Equity",
        margin=dict(l=10, r=10, t=40, b=10),
        height=320,
    )
    return fig


def render_equity_curve(
    equity_series: Sequence[float] | Sequence[EquityPoint] | pd.Series | pd.DataFrame,
    title: str = "Equity Curve",
    use_container_width: bool = True,
) -> None:
    """
    Renders the equity curve into Streamlit.
    - If Plotly is available: uses st.plotly_chart(fig)
    - Otherwise: shows a warning and falls back to st.line_chart
    """
    fig = equity_curve_chart(equity_series, title=title)
    if fig is not None:
        st.plotly_chart(fig, use_container_width=use_container_width)
        return

    st.warning("Plotly not installed, falling back to basic line chart.")
    df = _format_equity_dataframe(equity_series)
    if df.empty:
        st.info("No equity data available.")
        return
    fallback_df = df.set_index("timestamp")["equity"].to_frame()
    st.line_chart(fallback_df)


def exposure_chart(points: Iterable[EquityPoint] | Sequence[Any] | pd.DataFrame | pd.Series):
    df = _points_to_dataframe(points)
    if go is None or df.empty or "exposure" not in df.columns:
        return None

    fig = go.Figure(
        go.Bar(x=df["timestamp"], y=df["exposure"], marker=dict(color=_rgba((66, 153, 225)))),
    )
    fig.update_layout(margin=dict(l=0, r=0, t=30, b=0), height=280)
    return fig


def pacing_history_chart(history: Iterable[Decimal], max_rpm: Decimal):
    if go is None:
        return None

    values = [float(v) for v in history]
    fig = go.Figure(
        go.Scatter(y=values, mode="lines+markers", line=dict(color=_rgba((237, 137, 54)))),
    )
    fig.add_hline(y=float(max_rpm), line_dash="dash", line_color="red", annotation_text="Limit")
    fig.update_layout(margin=dict(l=0, r=0, t=20, b=0), height=260)
    return fig


def risk_gauge_chart(value: float, *, limit: float, title: str, suffix: str = ""):
    if go is None:
        return None

    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=value,
            title={"text": title},
            number={"suffix": suffix},
            gauge={
                "axis": {"range": [None, limit]},
                "bar": {"color": _rgba((56, 161, 105))},
                "steps": [
                    {"range": [0, limit * 0.6], "color": _rgba((72, 187, 120), 0.2)},
                    {"range": [limit * 0.6, limit * 0.85], "color": _rgba((237, 137, 54), 0.25)},
                    {"range": [limit * 0.85, limit], "color": _rgba((229, 62, 62), 0.2)},
                ],
            },
        )
    )
    fig.update_layout(margin=dict(l=0, r=0, t=50, b=0), height=220)
    return fig
