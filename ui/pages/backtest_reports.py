"""Backtest Reports page."""

from __future__ import annotations

import io
import pandas as pd
import streamlit as st

from ui.services.backend import BrokerAPI
from ui.state import AppSessionState
from ui.utils.charts import render_equity_curve
from ui.utils.format import fmt_currency, fmt_num, fmt_pct, fmt_signed_currency
from ui.utils.num import to_float
from ui.utils.report_metrics import (
    compute_cagr_from_equity,
    compute_cagr_from_return,
    get_field,
)


def _metrics(report) -> None:
    sharpe = get_field(report, ["sharpe", "sharpe_ratio"])
    win_rate = get_field(report, ["win_rate", "winrate", "win_ratio"])
    cagr = get_field(report, ["cagr", "annual_return", "cagr_pct"])
    max_dd = get_field(report, ["max_drawdown", "max_dd", "mdd"])

    if cagr is None:
        total_ret = get_field(report, ["total_return", "return_total", "total_ret"])
        days = get_field(report, ["duration_days", "days", "period_days"])
        days_value = to_float(days) if days is not None else None
        if total_ret is not None and days_value:
            cagr = compute_cagr_from_return(to_float(total_ret), days_value)
        if cagr is None:
            equity_curve = get_field(report, ["equity_curve", "equity", "equity_series"])

            def _edge_values(points):
                first_point = get_field(
                    points[0],
                    ["equity", "value", "balance", "nav", "close"],
                    default=points[0],
                )
                last_point = get_field(
                    points[-1],
                    ["equity", "value", "balance", "nav", "close"],
                    default=points[-1],
                )
                return to_float(first_point), to_float(last_point)

            duration_days = days_value or 365

            if isinstance(equity_curve, (list, tuple)) and len(equity_curve) >= 2:
                first, last = _edge_values(equity_curve)
                cagr = compute_cagr_from_equity(first, last, duration_days)
            elif isinstance(equity_curve, pd.Series) and len(equity_curve) >= 2:
                first = to_float(equity_curve.iloc[0])
                last = to_float(equity_curve.iloc[-1])
                cagr = compute_cagr_from_equity(first, last, duration_days)
            elif isinstance(equity_curve, pd.DataFrame) and len(equity_curve.index) >= 2:
                first_row = equity_curve.iloc[0]
                last_row = equity_curve.iloc[-1]
                first = to_float(
                    get_field(first_row, ["equity", "value", "balance", "nav", "close"], default=first_row)
                )
                last = to_float(
                    get_field(last_row, ["equity", "value", "balance", "nav", "close"], default=last_row)
                )
                cagr = compute_cagr_from_equity(first, last, duration_days)
            else:
                try:
                    sequence = list(equity_curve) if equity_curve is not None else []
                except TypeError:
                    sequence = []
                if len(sequence) >= 2:
                    first, last = _edge_values(sequence)
                    cagr = compute_cagr_from_equity(first, last, duration_days)

    def as_pct(value):
        val = to_float(value)
        if isinstance(val, (int, float)):
            return val / 100.0 if val > 1.5 else val
        return None

    win_rate = as_pct(win_rate)
    max_dd = as_pct(max_dd)
    cagr = as_pct(cagr)

    col1, col2, col3, col4 = st.columns(4)

    if sharpe is not None:
        sharpe_val = to_float(sharpe)
        if isinstance(sharpe_val, (int, float)):
            col1.metric("Sharpe", f"{sharpe_val:.2f}")
    if win_rate is not None:
        col2.metric("Win Rate", fmt_pct(win_rate))
    if cagr is not None:
        col3.metric("CAGR", fmt_pct(cagr))
    if max_dd is not None:
        col4.metric("Max Drawdown", fmt_pct(max_dd))


def _equity_section(report) -> None:
    st.subheader("Equity Curve")
    equity_curve = get_field(report, ["equity_curve", "equity", "equity_series"])

    if isinstance(equity_curve, pd.DataFrame):
        render_equity_curve(equity_curve)
        df = equity_curve.copy()
    elif isinstance(equity_curve, pd.Series):
        render_equity_curve(equity_curve)
        df = equity_curve.to_frame(name="equity").reset_index(drop=True)
    else:
        if equity_curve is None:
            points = []
        elif isinstance(equity_curve, (list, tuple)):
            points = list(equity_curve)
        else:
            try:
                points = list(equity_curve)
            except TypeError:
                points = [equity_curve]
        render_equity_curve(points)
        rows = []
        for point in points:
            if hasattr(point, "model_dump"):
                rows.append(point.model_dump())
            elif hasattr(point, "dict"):
                try:
                    rows.append(point.dict())
                except Exception:
                    continue
            elif isinstance(point, dict):
                rows.append(point)
        if rows:
            df = pd.DataFrame(rows)
        else:
            df = pd.DataFrame(points)
    buffer = io.StringIO()
    if not df.empty:
        df.to_csv(buffer, index=False)
    st.download_button(
        "Export equity curve CSV",
        buffer.getvalue().encode("utf-8"),
        file_name=f"{get_field(report, ['run_id', 'id', 'report_id'], default='report')}_equity.csv",
        mime="text/csv",
    )


def _trade_tree_placeholder() -> None:
    with st.expander("Trade tree / diagnostics"):
        st.write("Detailed trade attribution to be sourced from backend HTML report.")


def render(api: BrokerAPI, state: AppSessionState) -> None:  # noqa: ARG001
    st.title("Backtest Reports")
    runs = api.get_backtest_runs()
    run_ids = [get_field(run, ["run_id", "id", "uuid"]) for run in runs]
    run_ids = [run_id for run_id in run_ids if run_id is not None]
    if not run_ids:
        st.info("No backtest runs available.")
        return
    run_id = st.selectbox("Run", run_ids)
    report = api.get_backtest_report(run_id)

    _metrics(report)
    _equity_section(report)
    _trade_tree_placeholder()
    st.info("Open the HTML report from backend in future iteration.")
