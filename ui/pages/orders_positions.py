from __future__ import annotations

"""Orders & Positions page."""


from typing import List

import pandas as pd
import streamlit as st

from ui.components.tables import render_table
from ui.lib.api_client import ApiClient
from ui.lib.page_guard import require_backend
from ui.services.backend import BrokerAPI
from ui.state import AppSessionState, Order, Position


def _orders_table(orders: List[Order]) -> None:
    st.subheader("Live Orders")
    render_table("orders", [order.model_dump() for order in orders])
    if not orders:
        return
    with st.expander("Order diagnostics"):
        warnings = [order for order in orders if order.error]
        if warnings:
            st.error("\n".join(f"{order.order_id}: {order.error}" for order in warnings))
        else:
            st.success("No order errors flagged.")


def _order_actions(orders: List[Order], state: AppSessionState) -> None:
    st.subheader("Paper Controls")
    disabled = state.profile != "paper"
    col1, col2, col3 = st.columns(3)
    target_order = col1.selectbox(
        "Select Order",
        [order.order_id for order in orders] if orders else ["None"],
        disabled=disabled or not orders,
        key="order_select",
    )
    if col2.button("Cancel Selected", disabled=disabled or not orders):
        st.toast(f"Cancel requested for {target_order}", icon="📝")
    replace_price = col3.number_input("Replace Price", value=0.0, disabled=disabled or not orders)
    if st.button("Replace Order", disabled=disabled or not orders):
        st.toast(f"Replace {target_order} @ {replace_price}", icon="🔁")
    if st.button("Cancel All (Paper)", disabled=disabled):
        st.toast("Cancel all orders queued", icon="🛑")


def _positions_section(positions: List[Position]) -> None:
    st.subheader("Positions")
    render_table("positions", [position.model_dump() for position in positions])
    if not positions:
        return
    df = pd.DataFrame([position.model_dump() for position in positions])
    summary_cols = st.columns(4)
    summary_cols[0].metric("Net Qty", df["qty"].sum())
    summary_cols[1].metric("Unrealized", f"${df['unrealized'].sum():,.2f}")
    summary_cols[2].metric("Realized", f"${df['realized'].sum():,.2f}")
    summary_cols[3].metric("Avg Leverage", f"{df['leverage'].mean():.2f}")

    greeks = df[["delta", "gamma", "theta", "vega"]].sum()
    st.caption("Greeks: " + ", ".join(f"{name}={value:.2f}" for name, value in greeks.items()))


def render(api: BrokerAPI, state: AppSessionState) -> None:
    st.title("Orders & Positions")
    backend_guard = ApiClient()
    if not require_backend(backend_guard):
        st.stop()

    try:
        orders = api.get_orders()
    except Exception as exc:  # noqa: BLE001 - guard backend failures
        st.error(f"Failed to load orders: {exc}")
        orders = []

    try:
        positions = api.get_positions()
    except Exception as exc:  # noqa: BLE001 - guard backend failures
        st.error(f"Failed to load positions: {exc}")
        positions = []

    _orders_table(orders)
    _order_actions(orders, state)
    _positions_section(positions)
