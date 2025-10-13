"""Control Center page."""

from __future__ import annotations

import json
from difflib import unified_diff
from pathlib import Path
from typing import Dict

import streamlit as st

from ui.components.badges import status_pill
from ui.services.backend import BrokerAPI
from ui.state import AppSessionState, RiskSnapshot, update_session_state


def _load_config(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _render_status(status: Dict[str, str]) -> None:
    cols = st.columns(4)
    cols[0].metric("Profile", status.get("profile", "unknown"))
    cols[1].metric("Version", status.get("version", "n/a"))
    cols[2].metric("Clock", status.get("clock", "-"))
    cols[3].metric("Preset", status.get("preset", "balanced"))

    market_open = status.get("market_open", False)
    status_pill(
        "Market",
        "Open" if market_open else "Closed",
        variant="positive" if market_open else "warning",
    )
    status_pill(
        "Mode",
        "Paper" if status.get("paper", True) else "Live",
        variant="positive" if status.get("paper", True) else "warning",
    )
    halted = bool(status.get("halted"))
    status_pill(
        "Kill Switch",
        "Engaged" if halted else "Standby",
        variant="warning" if halted else "positive",
    )
    if status.get("trace_id"):
        st.caption(f"Trace ID {status['trace_id']}")
    if status.get("strategy_params"):
        st.caption("Strategy params: " + json.dumps(status["strategy_params"], indent=2))


def _diff_configs(default: str, current: str) -> str:
    diff = unified_diff(
        default.splitlines(),
        current.splitlines(),
        fromfile="defaults",
        tofile="current",
        lineterm="",
    )
    return "\n".join(diff) or "No overrides detected."


def _run_config_preview() -> None:
    st.subheader("Run Configuration")
    default_path = Path("config.example.yaml")
    current_path = Path("config.yaml")
    default_config = _load_config(default_path)
    current_config = _load_config(current_path) or default_config
    diff = _diff_configs(default_config, current_config)
    st.code(diff, language="diff")
    st.caption(
        "Comparing config.yaml to config.example.yaml. Defaults shown if no override present."
    )


def _action_buttons(api: BrokerAPI, state: AppSessionState, preset: str) -> None:
    st.subheader("Paper Trading Controls")
    col1, col2, col3 = st.columns(3)
    confirm_halt = st.checkbox("Confirm flatten & halt", key="confirm_halt")
    if col1.button("Start Paper", use_container_width=True):
        response = api.start_paper(preset)
        state.run_id = response.get("run_id")
        st.toast(f"Paper run started ({state.run_id})", icon="✅")
    if col2.button("Stop", use_container_width=True):
        api.stop_all()
        state.run_id = None
        st.toast("All paper runs stopped", icon="🛑")
    if col3.button("Flatten & Halt", use_container_width=True, disabled=not confirm_halt):
        api.flatten_and_halt()
        state.run_id = None
        st.toast("Flatten + halt triggered", icon="⛔")
    if not confirm_halt:
        st.caption("Enable the confirmation checkbox to activate the halt button.")


def _live_controls(api: BrokerAPI, state: AppSessionState, preset: str) -> None:
    st.subheader("Live Trading Controls")
    enable_live = st.checkbox("Enable live trading", key="enable_live")
    confirm_text = st.text_input(
        "Type CONFIRM to unlock Start Live",
        key="live_confirm",
        placeholder="CONFIRM",
    )
    armed = enable_live and confirm_text.strip().upper() == "CONFIRM"
    disabled = not armed
    if st.button("Start Live", use_container_width=True, disabled=disabled):
        try:
            response = api.start_live(preset)
        except Exception as exc:  # noqa: BLE001 - surface backend failures
            st.error(str(exc))
        else:
            state.run_id = response.get("run_id")
            st.toast(f"Live run started ({state.run_id})", icon="🚀")
    if not enable_live:
        st.caption("Check the box to enable live trading controls.")
    elif not armed:
        st.caption("Enter CONFIRM exactly to arm the live start button.")


def _risk_overview(snapshot: RiskSnapshot) -> None:
    st.subheader("Risk Snapshot")
    cols = st.columns(4)
    cols[0].metric("Daily Loss %", f"{snapshot.daily_loss_pct}%")
    cols[1].metric("Max Exposure", f"${snapshot.max_exposure:,.0f}")
    cols[2].metric("Open Positions", snapshot.open_positions)
    cols[3].metric("Leverage", snapshot.leverage)
    if snapshot.breached:
        items = ", ".join(f"{k}: {v}" for k, v in snapshot.breached.items())
        st.error(f"Thresholds breached → {items}")
        st.markdown("[Review Risk Presets](./RISK_PRESETS.md)")
    st.caption(f"Run ID: {snapshot.run_id or '—'}")


def render(api: BrokerAPI, state: AppSessionState) -> None:
    st.title("Control Center")
    try:
        status = api.get_status()
    except Exception as exc:  # noqa: BLE001 - surface backend failures
        st.error("Backend API is not reachable at the configured address.")
        st.code(f"{exc}")
        st.info("Start the API first, then click 'Retry'.")
        if st.button("Retry"):
            st.rerun()
        return
    update_session_state(last_trace_id=status.get("trace_id"))

    with st.sidebar:
        st.subheader("Run Preset")
        preset = st.selectbox(
            "Preset",
            ["safe", "balanced", "high_risk"],
            index=["safe", "balanced", "high_risk"].index(status.get("preset", "balanced")),
            help="Choose risk profile presets served by the backend",
        )

    _action_buttons(api, state, preset)
    _live_controls(api, state, preset)
    _render_status(status)

    snapshot: RiskSnapshot = api.get_risk_snapshot()
    _risk_overview(snapshot)

    _run_config_preview()
