"""Streamlit dashboard entrypoint."""
from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from core.config import load_config

CONFIG_PATH = Path(os.getenv("TRADE_CONFIG", "config.example.yaml"))


def render() -> None:
    st.set_page_config(page_title="Gigatrader", layout="wide")
    st.title("Gigatrader Paper Trading Dashboard")
    config = load_config(CONFIG_PATH)
    st.sidebar.header("Controls")
    st.sidebar.write(f"Profile: {config.profile}")
    risk_choice = st.sidebar.radio("Risk Mode", ["safe", "balanced", "high_risk"], index=0)
    st.sidebar.button("Start Paper Bot")
    st.sidebar.button("Stop Bot")

    st.metric("Risk Preset", risk_choice)
    st.subheader("Equity Curve")
    st.line_chart([0, 1, 0.5])
    st.subheader("Open Positions")
    st.write("No positions - scaffold placeholder")
    st.subheader("Recent Trades")
    st.table([])
    st.subheader("Why this trade?")
    st.write("Signals and risk checks will appear here once strategies are executed.")


if __name__ == "__main__":
    render()
