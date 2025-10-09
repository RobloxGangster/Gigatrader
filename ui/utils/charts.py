"""Chart helper utilities for the Gigatrader UI."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Iterable, List, Tuple

import plotly.graph_objects as go

from ui.state import EquityPoint


ColorSpec = Tuple[int, int, int]


def _rgba(color: ColorSpec, alpha: float = 1.0) -> str:
    return f"rgba({color[0]}, {color[1]}, {color[2]}, {alpha})"


def equity_curve_chart(points: Iterable[EquityPoint]) -> go.Figure:
    """Create an equity and drawdown Plotly chart."""
    timestamps: List[datetime] = []
    equity: List[float] = []
    drawdown: List[float] = []

    for point in points:
        timestamps.append(point.timestamp)
        equity.append(float(point.equity))
        drawdown.append(float(point.drawdown))

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=timestamps,
            y=equity,
            name="Equity",
            mode="lines",
            line=dict(color=_rgba((56, 161, 105))),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=timestamps,
            y=drawdown,
            name="Drawdown",
            mode="lines",
            line=dict(color=_rgba((229, 62, 62))),
            fill="tozeroy",
            fillcolor=_rgba((229, 62, 62), 0.1),
        )
    )
    fig.update_layout(margin=dict(l=0, r=0, t=30, b=0), height=320)
    return fig


def exposure_chart(points: Iterable[EquityPoint]) -> go.Figure:
    """Create an exposure over time chart."""
    timestamps: List[datetime] = []
    exposure: List[float] = []
    for point in points:
        timestamps.append(point.timestamp)
        exposure.append(float(point.exposure))

    fig = go.Figure(
        go.Bar(x=timestamps, y=exposure, marker=dict(color=_rgba((66, 153, 225)))),
    )
    fig.update_layout(margin=dict(l=0, r=0, t=30, b=0), height=280)
    return fig


def pacing_history_chart(history: Iterable[Decimal], max_rpm: Decimal) -> go.Figure:
    values = [float(v) for v in history]
    fig = go.Figure(
        go.Scatter(y=values, mode="lines+markers", line=dict(color=_rgba((237, 137, 54)))),
    )
    fig.add_hline(y=float(max_rpm), line_dash="dash", line_color="red", annotation_text="Limit")
    fig.update_layout(margin=dict(l=0, r=0, t=20, b=0), height=260)
    return fig


def risk_gauge_chart(value: float, *, limit: float, title: str, suffix: str = "") -> go.Figure:
    """Render a gauge showing utilisation vs. limit."""
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


