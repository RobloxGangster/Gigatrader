"""Control Center page."""

from __future__ import annotations

import json
from difflib import unified_diff
from pathlib import Path
from typing import Any, Dict, List

import time
import streamlit as st

from ui.components.badges import status_pill
from ui.components.tables import render_table
from ui.services.backend import BrokerAPI
from ui.state import (
    AppSessionState,
    Order,
    Position,
    RiskSnapshot,
    update_session_state,
)
from ui.utils.compat import rerun as st_rerun
from ui.utils.format import fmt_currency, fmt_pct, fmt_signed_currency
from ui.utils.num import to_float
from ui.utils.runtime import get_runtime_flags


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


def _action_buttons(
    api: BrokerAPI, state: AppSessionState, preset: str, mock_mode: bool
) -> None:
    st.subheader("Paper Trading Controls")
    col1, col2, col3 = st.columns(3)
    confirm_halt = st.checkbox("Confirm flatten & halt", key="confirm_halt")
    start_paper = col1.button(
        "Start Paper",
        disabled=mock_mode,
        help="Disabled in Mock mode; flip MOCK_MODE=false to send to Alpaca paper.",
    )
    if start_paper and not mock_mode:
        response = api.start_paper(preset)
        state.run_id = response.get("run_id")
        st.toast(f"Paper run started ({state.run_id})", icon="✅")
    stop_runs = col2.button(
        "Stop",
        disabled=mock_mode,
        help="Disabled in Mock mode.",
    )
    if stop_runs and not mock_mode:
        api.stop_all()
        state.run_id = None
        st.toast("All paper runs stopped", icon="🛑")
    flatten_halt = col3.button(
        "Flatten & Halt",
        disabled=(mock_mode or not confirm_halt),
        help="Disabled in Mock mode; requires confirmation when enabled.",
    )
    if flatten_halt and not mock_mode and confirm_halt:
        api.flatten_and_halt()
        state.run_id = None
        st.toast("Flatten + halt triggered", icon="⛔")
    if not confirm_halt:
        st.caption("Enable the confirmation checkbox to activate the halt button.")


def _live_controls(
    api: BrokerAPI, state: AppSessionState, preset: str, mock_mode: bool
) -> None:
    st.subheader("Live Trading Controls")
    enable_live = st.checkbox("Enable live trading", key="enable_live")
    confirm_text = st.text_input(
        "Type CONFIRM to unlock Start Live",
        key="live_confirm",
        placeholder="CONFIRM",
    )
    armed = enable_live and confirm_text.strip().upper() == "CONFIRM"
    disabled = not armed
    start_live = st.button(
        "Start Live",
        disabled=(disabled or mock_mode),
        help="Disabled in Mock mode; flip MOCK_MODE=false to send to Alpaca paper.",
    )
    if start_live and not mock_mode:
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
    cols = st.columns(5)
    cols[0].metric("Equity", fmt_currency(snapshot.equity))
    cols[1].metric("Cash", fmt_currency(snapshot.cash))
    cols[2].metric("Daily P&L", fmt_signed_currency(snapshot.day_pnl))
    cols[3].metric("Leverage", f"{to_float(snapshot.leverage):.2f}×")
    cols[4].metric("Open Positions", int(snapshot.open_positions))

    cols = st.columns(3)
    cols[0].metric("Daily Loss %", fmt_pct(snapshot.daily_loss_pct))
    cols[1].metric("Exposure %", fmt_pct(snapshot.exposure_pct))
    cols[2].metric("Max Exposure", fmt_currency(snapshot.max_exposure, digits=0))

    if snapshot.breached:
        if snapshot.kill_switch:
            st.error("Kill switch engaged – trading halted.")
        else:
            st.error("Risk thresholds breached – review presets and positions.")
        st.markdown("[Review Risk Presets](./RISK_PRESETS.md)")
    st.caption(
        f"Profile: {snapshot.profile} · Run ID: {snapshot.run_id or '—'} · Updated {snapshot.timestamp}"
    )


def _orders_preview(orders: List[Order]) -> None:
    st.subheader("Orders Snapshot")
    if not orders:
        st.caption("No working orders.")
        return
    render_table("cc_orders", [order.model_dump() for order in orders], page_size=5)


def _positions_preview(positions: List[Position]) -> None:
    st.subheader("Positions Snapshot")
    if not positions:
        st.caption("No open positions.")
        return
    render_table("cc_positions", [position.model_dump() for position in positions], page_size=5)


def render(api: BrokerAPI, state: AppSessionState) -> None:
    st.title("Control Center")
    st.markdown('<div data-testid="page-control-center"></div>', unsafe_allow_html=True)
    st.markdown('<div data-testid="control-center-root"></div>', unsafe_allow_html=True)
    st.header("Control Center")
    st.caption("CONTROL_CENTER_READY")
    try:
        status = api.get_status()
    except Exception as exc:  # noqa: BLE001 - surface backend failures
        st.error("Backend API is not reachable at the configured address.")
        st.code(f"{exc}")
        st.info("Start the API first, then click 'Retry'.")
        if st.button("Retry"):
            st_rerun()
        return
    update_session_state(last_trace_id=status.get("trace_id"))

    metrics: Dict[str, Any] = {}
    try:
        metrics = api.get_metrics()
    except Exception:  # noqa: BLE001 - metrics are optional
        metrics = {}

    stream_flag = metrics.get("alpaca_stream_connected")
    stream_note = "offline"
    if isinstance(stream_flag, (int, float)):
        stream_note = "connected" if int(stream_flag) else "offline"

    flags = get_runtime_flags(api)
    mock_mode = flags.mock_mode

    snapshot: RiskSnapshot = api.get_risk_snapshot()
    acct: Dict[str, Any] = {}
    if not mock_mode:
        try:
            acct = api.get_account()
        except Exception as exc:  # noqa: BLE001 - surface to UI
            st.warning(f"Failed to load account: {exc}")
            acct = {}
    if mock_mode:
        st.info(
            "Mock mode is ON: trading actions are disabled here. "
            "Set MOCK_MODE=false and relaunch to place real paper orders."
        )
    st.caption("Mode: 🧪 MOCK" if mock_mode else "Mode: ✅ PAPER")
    st.caption(f"OMS: SQLite active · Stream: {stream_note}")

    st.subheader("Run Preset")
    preset = st.selectbox(
        "Preset",
        ["safe", "balanced", "high_risk"],
        index=["safe", "balanced", "high_risk"].index(status.get("preset", "balanced")),
        help="Choose risk profile presets served by the backend",
        key="preset_selector",
    )

    _action_buttons(api, state, preset, mock_mode)
    _live_controls(api, state, preset, mock_mode)
    _render_status(status)

    pv = acct.get("portfolio_value") or acct.get("equity")
    cash = acct.get("cash")
    bp = acct.get("buying_power")
    st.subheader("Account")
    c1, c2, c3 = st.columns(3)

    def _fmt(value: Any, digits: int = 2) -> str:
        try:
            return f"{float(value):,.{digits}f}"
        except (TypeError, ValueError):
            return "—"

    c1.metric("Portfolio Value", _fmt(pv))
    c2.metric("Cash", _fmt(cash))
    c3.metric("Buying Power", _fmt(bp))

    st.divider()

    _risk_overview(snapshot)

    sync_col, refresh_col, ts_col = st.columns([1, 1, 2])
    if sync_col.button(
        "Sync Now",
        help="Fetch latest from Alpaca",
        disabled=mock_mode,
    ):
        try:
            api._request("POST", "/orders/sync")
        except Exception as exc:  # noqa: BLE001 - network failures
            st.error(f"Sync failed: {exc}")
        else:
            st.success("Synced from Alpaca.")
            st.session_state["__last_sync_ts__"] = int(time.time())
            st.rerun()

    if refresh_col.button("Refresh"):
        st_rerun()

    last_ts = st.session_state.get("__last_sync_ts__")
    if last_ts:
        ts_col.caption(
            f"Last sync: {time.strftime('%H:%M:%S', time.localtime(last_ts))}"
        )
    else:
        ts_col.caption("Last sync: —")

    try:
        orders = api.get_orders()
    except Exception as exc:  # noqa: BLE001 - surface backend failures
        st.error(f"Orders failed to load: {exc}")
        orders = []

    try:
        positions = api.get_positions()
    except Exception as exc:  # noqa: BLE001 - surface backend failures
        st.error(f"Positions failed to load: {exc}")
        positions = []
    _orders_preview(orders)
    _positions_preview(positions)

    _run_config_preview()
