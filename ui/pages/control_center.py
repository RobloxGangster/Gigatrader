from __future__ import annotations

import os
from typing import Any, Dict, Iterable

import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")


def _get(path: str) -> Any:
    resp = requests.get(f"{API_URL}{path}", timeout=8)
    resp.raise_for_status()
    return resp.json()


def _fmt_money(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"${number:,.2f}"


def _trim_order(order: Dict[str, Any]) -> Dict[str, Any]:
    keep = (
        "symbol",
        "side",
        "qty",
        "type",
        "limit_price",
        "status",
        "filled_qty",
        "submitted_at",
    )
    return {key: order.get(key) for key in keep}


def _trim_position(position: Dict[str, Any]) -> Dict[str, Any]:
    keep = (
        "symbol",
        "qty",
        "avg_entry_price",
        "market_value",
        "unrealized_pl",
    )
    return {key: position.get(key) for key in keep}


def render(*_, **__) -> None:
    """Render the paper-trading control center dashboard."""

    st.title("Control Center")
    st.caption("Alpaca paper dashboard mirror")

    try:
        account = _get("/broker/account")
        positions: Iterable[Dict[str, Any]] = _get("/broker/positions")
        orders: Iterable[Dict[str, Any]] = _get("/broker/orders")
        stream_status = _get("/stream/status")
    except Exception as exc:  # noqa: BLE001 - show inline error
        st.error(f"Control Center error: {exc}")
        return

    col_equity, col_cash, col_bp = st.columns(3)
    col_equity.metric("Equity", _fmt_money(account.get("equity")))
    col_cash.metric("Cash", _fmt_money(account.get("cash")))
    col_bp.metric("Buying Power", _fmt_money(account.get("buying_power")))

    st.subheader("Positions")
    pos_rows = [_trim_position(p) for p in positions or []]
    if pos_rows:
        st.dataframe(pos_rows, use_container_width=True)
    else:
        st.write("No open positions.")

    st.subheader("Recent Orders")
    order_rows = [_trim_order(o) for o in orders or []]
    if order_rows:
        st.dataframe(order_rows, use_container_width=True)
    else:
        st.write("No recent orders.")

    st.subheader("Market Stream")
    status_text = stream_status.get("status", "offline")
    st.write(f"Stream: **{status_text}**")
    last_error = stream_status.get("last_error")
    if last_error:
        st.caption(f"last_error: {last_error}")
