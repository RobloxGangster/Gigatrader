"""Equity & Risk page."""
from __future__ import annotations

from statistics import mean

import pandas as pd
import streamlit as st

from ui.services.backend import BrokerAPI
from ui.state import AppSessionState, EquityPoint
from ui.utils.charts import equity_curve_chart, exposure_chart, risk_gauge_chart


def _equity_summary(points: list[EquityPoint]) -> None:
    st.subheader("Equity Overview")
    st.plotly_chart(equity_curve_chart(points), use_container_width=True)
    st.plotly_chart(exposure_chart(points), use_container_width=True)

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
    cols[0].plotly_chart(
        risk_gauge_chart(abs(float(snapshot.daily_loss_pct)), limit=8, title="Daily Loss", suffix="%"),
        use_container_width=True,
    )
    cols[1].plotly_chart(
        risk_gauge_chart(current_exposure, limit=100, title="Exposure", suffix="%"),
        use_container_width=True,
    )
    cols[2].plotly_chart(
        risk_gauge_chart(float(snapshot.open_positions), limit=20, title="Open Positions"),
        use_container_width=True,
    )
    cols[3].plotly_chart(
        risk_gauge_chart(float(snapshot.leverage), limit=6, title="Leverage"),
        use_container_width=True,
    )


def _risk_table(snapshot) -> None:
    st.subheader("Risk Snapshot")
    df = pd.DataFrame(
        [
            {"Metric": "Daily Loss %", "Value": snapshot.daily_loss_pct},
            {"Metric": "Max Exposure ($)", "Value": snapshot.max_exposure},
            {"Metric": "Open Positions", "Value": snapshot.open_positions},
            {"Metric": "Leverage", "Value": snapshot.leverage},
        ]
    )
    st.dataframe(df, hide_index=True)
    if snapshot.breached:
        st.error("Alerts: " + ", ".join(f"{k}={v}" for k, v in snapshot.breached.items()))
        st.markdown("[Risk Presets Documentation](./RISK_PRESETS.md)")


def render(api: BrokerAPI, state: AppSessionState) -> None:
    st.title("Equity & Risk")
    points = api.get_equity_curve(state.run_id)
    snapshot = api.get_risk_snapshot()

    if not points:
        st.warning("No equity data available.")
        return

    _equity_summary(points)
    _risk_dials(points, snapshot)
    _risk_table(snapshot)

