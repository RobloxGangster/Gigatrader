from __future__ import annotations

"""Equity & Risk page."""


from statistics import mean

import pandas as pd
import streamlit as st

from ui.lib.api_client import ApiClient
from ui.lib.page_guard import require_backend
from ui.services.backend import BrokerAPI
from ui.utils.num import to_float
from ui.state import AppSessionState, EquityPoint
from ui.utils.charts import exposure_chart, render_equity_curve, risk_gauge_chart


def _equity_summary(points: list[EquityPoint]) -> None:
    st.subheader("Equity Overview")
    render_equity_curve(points)

    exposure_fig = exposure_chart(points)
    if exposure_fig is not None:
        st.plotly_chart(exposure_fig, width="stretch")
    else:
        st.warning("Plotly not installed, showing basic exposure line chart.")
        exposure_df = pd.DataFrame(
            {
                "timestamp": [point.timestamp for point in points],
                "exposure": [float(point.exposure) for point in points],
            }
        )
        exposure_df["timestamp"] = pd.to_datetime(exposure_df["timestamp"])
        st.line_chart(exposure_df.set_index("timestamp")["exposure"].to_frame())

    trailing_points = points[-10:]
    avg_drawdown = mean(float(point.drawdown) for point in trailing_points)
    stat_cols = st.columns(3)
    stat_cols[0].metric("Last Equity", f"${float(points[-1].equity):,.0f}")
    stat_cols[1].metric("Avg Drawdown (10)", f"{avg_drawdown:.2f}%")
    stat_cols[2].metric("Exposure Now", f"{float(points[-1].exposure):.1f}%")


def _risk_dials(points: list[EquityPoint], snapshot) -> None:
    st.subheader("Risk Dials")
    current_exposure = float(points[-1].exposure)
    cols = st.columns(4)
    fallback_used = False

    def _render_gauge(col, value: float, *, limit: float, title: str, suffix: str = "") -> bool:
        fig = risk_gauge_chart(value, limit=limit, title=title, suffix=suffix)
        if fig is not None:
            col.plotly_chart(fig, width="stretch")
            return False
        formatted_value = f"{value:.2f}{suffix}" if suffix else f"{value:.2f}"
        col.metric(title, formatted_value)
        return True

    daily_loss = abs(to_float(snapshot.daily_loss_pct) * 100)
    fallback_used |= _render_gauge(
        cols[0], daily_loss, limit=8, title="Daily Loss", suffix="%"
    )
    fallback_used |= _render_gauge(
        cols[1], current_exposure, limit=100, title="Exposure", suffix="%"
    )
    fallback_used |= _render_gauge(
        cols[2], float(snapshot.open_positions), limit=20, title="Open Positions"
    )
    fallback_used |= _render_gauge(
        cols[3], to_float(snapshot.leverage), limit=6, title="Leverage"
    )

    if fallback_used:
        st.warning("Plotly not installed, displaying numeric values instead of gauges.")


def _risk_table(snapshot) -> None:
    st.subheader("Risk Snapshot")
    df = pd.DataFrame(
        [
            {"Metric": "Daily Loss %", "Value": f"{to_float(snapshot.daily_loss_pct) * 100:.2f}%"},
            {"Metric": "Max Exposure ($)", "Value": f"${to_float(snapshot.max_exposure):,.0f}"},
            {"Metric": "Open Positions", "Value": int(snapshot.open_positions)},
            {"Metric": "Leverage", "Value": f"{to_float(snapshot.leverage):.2f}×"},
        ]
    )
    st.dataframe(df, hide_index=True)
    if snapshot.breached:
        if snapshot.kill_switch:
            st.error("Kill switch engaged – trading halted.")
        else:
            st.error("Risk thresholds breached – review presets and positions.")
        st.markdown("[Risk Presets Documentation](./RISK_PRESETS.md)")


def render(api: BrokerAPI, state: AppSessionState) -> None:
    st.title("Equity & Risk")
    backend_guard = ApiClient()
    if not require_backend(backend_guard):
        st.stop()

    try:
        points = api.get_equity_curve(state.run_id)
    except Exception as exc:  # noqa: BLE001 - guard backend failures
        st.error(f"Failed to load equity curve: {exc}")
        return

    try:
        snapshot = api.get_risk_snapshot()
    except Exception as exc:  # noqa: BLE001 - guard backend failures
        st.error(f"Failed to load risk snapshot: {exc}")
        return

    if not points:
        st.warning("No equity data available.")
        return

    _equity_summary(points)
    _risk_dials(points, snapshot)
    _risk_table(snapshot)
