"""Strategy tuning page."""

from __future__ import annotations

import json

import streamlit as st

from ui.lib.api_client import ApiClient
from ui.lib.page_guard import require_backend
from ui.services.backend import BrokerAPI
from ui.state import AppSessionState


def render(api: BrokerAPI, state: AppSessionState) -> None:
    st.title("Strategy Tuning")
    st.caption("Adjust strategy parameters and preview backend configuration profiles.")

    backend_guard = ApiClient()
    if not require_backend(backend_guard):
        st.stop()

    presets = ["safe", "balanced", "high_risk"]
    default_preset = state.profile if state.profile in presets else "balanced"
    preset = st.selectbox("Preset", presets, index=presets.index(default_preset), key="tuning_preset")

    st.subheader("Risk Controls")
    max_positions = st.slider("Max Open Positions", min_value=1, max_value=20, value=10)
    target_allocation = st.slider("Target Allocation %", min_value=10, max_value=100, value=50, step=5)
    stop_loss = st.slider("Stop Loss %", min_value=1, max_value=20, value=5)
    take_profit = st.slider("Take Profit %", min_value=1, max_value=40, value=12)

    st.subheader("Simulation Preview")
    submitted = st.button("Preview Strategy Impact", key="btn_preview_strategy")
    if submitted:
        st.info(
            "Preview request sent — adjust parameters in the backend to apply changes."
        )

    try:
        metrics = api.get_metrics()
    except Exception as exc:  # noqa: BLE001 - optional metrics
        st.warning(f"Metrics unavailable: {exc}")
        metrics = {}

    if metrics:
        st.subheader("Live Metrics Snapshot")
        st.json(json.loads(json.dumps(metrics)))

    st.subheader("Proposed Configuration")
    config = {
        "preset": preset,
        "max_positions": max_positions,
        "target_allocation_pct": target_allocation,
        "stop_loss_pct": stop_loss,
        "take_profit_pct": take_profit,
    }
    st.code(json.dumps(config, indent=2), language="json")
