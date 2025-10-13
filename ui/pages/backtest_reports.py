"""Backtest Reports page."""

from __future__ import annotations

import io
import pandas as pd
import streamlit as st

from ui.services.backend import BrokerAPI
from ui.state import AppSessionState
from ui.utils.charts import equity_curve_chart


def _metrics(report) -> None:
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Sharpe", report.sharpe)
    col2.metric("Sortino", report.sortino)
    col3.metric("MDD", report.max_drawdown)
    col4.metric("Win Rate", report.win_rate)
    col5.metric("Turnover", report.turnover)


def _equity_section(report) -> None:
    st.subheader("Equity Curve")
    st.plotly_chart(equity_curve_chart(report.equity_curve), use_container_width=True)
    df = pd.DataFrame([point.model_dump() for point in report.equity_curve])
    buffer = io.StringIO()
    df.to_csv(buffer, index=False)
    st.download_button(
        "Export equity curve CSV",
        buffer.getvalue().encode("utf-8"),
        file_name=f"{report.run_id}_equity.csv",
        mime="text/csv",
    )


def _trade_tree_placeholder() -> None:
    with st.expander("Trade tree / diagnostics"):
        st.write("Detailed trade attribution to be sourced from backend HTML report.")


def render(api: BrokerAPI, state: AppSessionState) -> None:  # noqa: ARG001
    st.title("Backtest Reports")
    runs = api.get_backtest_runs()
    run_ids = [run.run_id for run in runs]
    if not run_ids:
        st.info("No backtest runs available.")
        return
    run_id = st.selectbox("Run", run_ids)
    report = api.get_backtest_report(run_id)

    _metrics(report)
    _equity_section(report)
    _trade_tree_placeholder()
    st.info("Open the HTML report from backend in future iteration.")
