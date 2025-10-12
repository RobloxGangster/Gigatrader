from __future__ import annotations

import subprocess
from pathlib import Path
import sys
from typing import List

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ui.services import runtime

load_dotenv()

if "symbols_input" not in st.session_state:
    st.session_state["symbols_input"] = "AAPL,MSFT"
if "streaming" not in st.session_state:
    st.session_state["streaming"] = False
if "last_backtest_output" not in st.session_state:
    st.session_state["last_backtest_output"] = ""
if "backtest_config" not in st.session_state:
    st.session_state["backtest_config"] = "config.yaml"

st.set_page_config(page_title="Gigatrader Control Panel", layout="wide")
st.title("Gigatrader Dev Console")

overview_tab, orders_tab, backtest_tab, logs_tab = st.tabs(
    ["Overview", "Orders", "Backtest", "Logs"]
)


def _parse_symbols(raw: str) -> List[str]:
    return [token.strip().upper() for token in raw.split(",") if token.strip()]


with overview_tab:
    st.subheader("Market Data Overview")
    st.caption("Start the live stream to monitor bar latency and staleness.")
    st.session_state["symbols_input"] = st.text_input(
        "Symbols", st.session_state["symbols_input"], help="Comma separated list"
    )
    cols = st.columns(3)
    start_clicked = cols[0].button("Start Stream", use_container_width=True)
    stop_clicked = cols[1].button("Stop Stream", use_container_width=True)
    refresh_clicked = cols[2].button("Refresh", use_container_width=True)

    if start_clicked:
        symbols = _parse_symbols(st.session_state["symbols_input"])
        if symbols:
            runtime.start_stream(symbols)
            st.session_state["streaming"] = True
            st.success(f"Streaming started for {', '.join(symbols)}")
        else:
            st.warning("Provide at least one symbol.")
        st.experimental_rerun()
    if stop_clicked:
        runtime.stop_stream()
        st.session_state["streaming"] = False
        st.info("Streaming stopped.")
        st.experimental_rerun()
    if refresh_clicked:
        st.experimental_rerun()

    health = runtime.get_stream_health()
    with st.container():
        cols = st.columns(4)
        cols[0].metric("Feed", health.get("feed", "n/a"))
        cols[1].metric("Threshold (s)", health.get("threshold_s", "n/a"))
        cols[2].metric("Active Symbols", len(health.get("ok", [])))
        cols[3].metric("Stale Symbols", len(health.get("stale", [])))
        if health.get("stale"):
            st.warning(f"Stale: {', '.join(health['stale'])}")
        elif st.session_state.get("streaming"):
            st.success("All symbols healthy.")

    bars = runtime.get_latest_bars()
    if bars:
        df = pd.DataFrame(bars)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No bar data yet.")

    samples = runtime.get_latency_samples()
    fig = go.Figure()
    for sym, values in samples.items():
        if values:
            fig.add_trace(go.Box(y=values, name=sym, boxmean=True))
    if fig.data:
        fig.update_layout(title="Latency Distribution", yaxis_title="Latency (s)")
        st.plotly_chart(fig, use_container_width=True)
    elif st.session_state.get("streaming"):
        st.caption("Waiting for latency samples...")

    account = runtime.get_account_summary()
    st.subheader("Account Summary")
    if "error" in account:
        st.error(account["error"])
    else:
        cols = st.columns(3)
        cols[0].metric("Status", account.get("status", "unknown"))
        cols[1].metric("Equity", account.get("equity", "n/a"))
        cols[2].metric("Cash", account.get("cash", "n/a"))

with orders_tab:
    st.subheader("Paper Test Orders")
    with st.form("order_form"):
        symbol = st.text_input("Symbol", "AAPL")
        qty = st.number_input("Quantity", min_value=1, value=1, step=1)
        order_type = st.selectbox("Order Type", ["market", "limit"])
        limit_price = None
        if order_type == "limit":
            limit_price = st.number_input(
                "Limit Price", min_value=0.0, value=0.0, step=0.01, format="%.2f"
            )
        submitted = st.form_submit_button("Submit Order")
    if submitted:
        try:
            if order_type == "limit" and not limit_price:
                raise ValueError("Limit orders require a positive limit price")
            result = runtime.place_test_order(
                symbol=symbol.strip().upper(),
                qty=int(qty),
                order_type=order_type,
                limit_price=float(limit_price) if limit_price else None,
            )
            st.success(f"Order submitted: {result}")
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))

with backtest_tab:
    st.subheader("Backtest Runner")
    st.session_state["backtest_config"] = st.text_input(
        "Config Path", st.session_state["backtest_config"]
    )
    if st.button("Run Backtest"):
        cfg = st.session_state["backtest_config"]
        cmd = ["python", "-m", "app.cli", "backtest"]
        if cfg:
            cmd.extend(["--config", cfg])
        result = subprocess.run(cmd, capture_output=True, text=True)
        output = result.stdout + "\n" + result.stderr
        st.session_state["last_backtest_output"] = output
        if result.returncode == 0:
            st.success("Backtest completed.")
        else:
            st.error("Backtest failed. See logs below.")
    if st.session_state["last_backtest_output"]:
        st.code(st.session_state["last_backtest_output"], language="bash")

    reports_path = Path("reports")
    if reports_path.exists():
        reports = sorted(
            reports_path.glob("*_report.html"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        if reports:
            st.markdown("### Latest Reports")
            for report in reports[:5]:
                rel_path = report.relative_to(Path.cwd()) if report.is_absolute() else report
                st.markdown(f"- [{report.name}]({rel_path.as_posix()})")
        else:
            st.info("No reports found.")
    else:
        st.info("Reports directory missing.")

with logs_tab:
    st.subheader("Logs")
    st.info("Log streaming coming soon. Monitor console output for now.")
