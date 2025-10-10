from __future__ import annotations
import os, subprocess, sys, time, pathlib
import streamlit as st
import pandas as pd
import plotly.express as px
from dotenv import load_dotenv

from app.streaming import _select_feed_with_probe
from ui.services.runtime import StreamManager, get_account_summary, place_test_order

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

st.set_page_config(page_title="Gigatrader UI", layout="wide")

st.sidebar.title("Gigatrader")
acct = {}
try:
    acct = get_account_summary()
    st.sidebar.success(f"{acct['mode']}  •  {acct['status']}")
    st.sidebar.write(f"Acct: `{acct['id']}`")
    st.sidebar.write(f"BP: ${acct['buying_power']}")
    st.sidebar.write(f"Cash: ${acct['cash']}")
    st.sidebar.write(f"Equity: ${acct['portfolio_value']}")
except Exception as e:
    st.sidebar.error(f"Account check failed: {e}")

if "stream" not in st.session_state:
    st.session_state.stream = StreamManager()

tab_dash, tab_orders, tab_backtest, tab_logs = st.tabs(["Overview", "Orders", "Backtest", "Logs"])

with tab_dash:
    st.subheader("Feed & Stream")
    feed = "?"
    try:
        feed = str(_select_feed_with_probe()).split(".")[-1]
    except Exception as e:
        st.warning(f"Feed selection error: {e}")
    col1, col2 = st.columns(2)
    with col1:
        syms = st.text_input("Symbols (comma-separated)", "AAPL,MSFT,SPY")
    with col2:
        run_btn = st.button("Start Stream", type="primary")
        stop_btn = st.button("Stop Stream")

    mgr: StreamManager = st.session_state.stream
    if run_btn:
        mgr.start([s.strip() for s in syms.split(",") if s.strip()])
        time.sleep(0.2)
    if stop_btn:
        mgr.stop()

    snap = mgr.snapshot()
    st.info(f"Feed: **{feed}**  •  Running: **{mgr.running}**  •  Stale threshold: {os.getenv('DATA_STALENESS_SEC','5')}s")
    colA, colB = st.columns([3,2])

    with colA:
        if snap.latest:
            rows = [{"symbol": s, "close": d["close"], "timestamp": d["ts"]} for s,d in snap.latest.items()]
            df = pd.DataFrame(rows).sort_values("symbol")
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.write("No bars received yet.")

    with colB:
        lat_rows = []
        for sym, L in snap.latencies.items():
            for v in L[-200:]:
                lat_rows.append({"symbol": sym, "latency_s": v})
        if lat_rows:
            dlat = pd.DataFrame(lat_rows)
            fig = px.box(dlat, x="symbol", y="latency_s", points="all")
            st.plotly_chart(fig, use_container_width=True)
        st.warning(f"STALE: {', '.join(snap.stale) if snap.stale else '—'}")

with tab_orders:
    st.subheader("Place Paper Test Order")
    colL, colR = st.columns(2)
    with colL:
        typ = st.selectbox("Order Type", ["market", "limit"])
        sym = st.text_input("Symbol", "AAPL")
        qty = st.number_input("Quantity", min_value=1, value=1, step=1)
        lmt = None
        if typ == "limit":
            lmt = st.number_input("Limit Price", min_value=0.0, value=200.0, step=0.1, format="%.2f")
        go = st.button("Submit Test Order (paper)")
    with colR:
        st.info("Paper only. Validates limit price locally; refuses in LIVE.")
    if go:
        try:
            res = place_test_order(sym.upper(), int(qty), typ, lmt)
            st.success(f"Submitted: {res['id']} • status={res['status']}")
        except Exception as e:
            st.error(str(e))

with tab_backtest:
    st.subheader("Run Backtest (stub)")
    days = st.number_input("Lookback days", min_value=1, value=5, step=1)
    uni = st.text_input("Universe (comma-separated)", "AAPL,MSFT")
    run = st.button("Run Backtest")
    if run:
        try:
            cmd = [sys.executable, "-m", "app.cli", "backtest", "--config", str(REPO_ROOT / "config.yaml"), "--days", str(int(days)), "--universe", uni]
            res = subprocess.run(cmd, capture_output=True, text=True)
            st.code(res.stdout + "
" + res.stderr)
            reports = sorted((REPO_ROOT / "reports").glob("*_report.html"))
            if reports:
                st.success(f"Report: {reports[-1].as_posix()}")
                st.markdown(f"[Open latest report]({reports[-1].as_uri()})")
        except Exception as e:
            st.error(str(e))

with tab_logs:
    st.subheader("Notes & Logs")
    st.write("Stream and order outcomes surface inline on other tabs. Consider wiring structured logs here later.")
