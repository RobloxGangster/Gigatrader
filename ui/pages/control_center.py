from __future__ import annotations

import os
import time
from typing import Any, Dict, Iterable, List, Tuple

import streamlit as st

try:  # pragma: no cover - optional dependency
    from streamlit_autorefresh import st_autorefresh  # type: ignore
except Exception:  # pragma: no cover - fallback when extra not installed
    def st_autorefresh(*, interval: int, key: str) -> int:
        count_key = f"__autorefresh_count__{key}"
        last_key = f"__autorefresh_last__{key}"
        now = time.time()
        last = float(st.session_state.get(last_key, 0.0))
        if now - last >= interval / 1000.0:
            st.session_state[last_key] = now
            st.session_state[count_key] = int(st.session_state.get(count_key, 0)) + 1
            st.rerun()
        return int(st.session_state.get(count_key, 0))

from ui.components.badges import status_pill
from ui.components.tables import render_table
from ui.services.backend import BrokerAPI
from ui.lib.api_client import ApiClient
from ui.lib.page_guard import require_backend
from ui.state import AppSessionState, update_session_state
from ui.utils.format import fmt_currency, fmt_pct, fmt_signed_currency
from ui.utils.num import to_float

_TESTING = "PYTEST_CURRENT_TEST" in os.environ
REFRESH_INTERVAL_SEC = 5
STATUS_POLL_INTERVAL = 1.5
STATUS_POLL_WINDOW = 2.0
DEFAULT_PRESETS: Tuple[str, ...] = ("safe", "balanced", "high_risk")
STRATEGY_LABELS: Dict[str, str] = {
    "intraday_momo": "Intraday Momentum",
    "intraday_revert": "Intraday Mean Reversion",
    "swing_breakout": "Swing Breakout",
}
def _fmt_money(value: Any, digits: int = 2) -> str:
    try:
        return fmt_currency(to_float(value), digits=digits)
    except Exception:  # noqa: BLE001 - defensive
        return "—"


def _fmt_signed(value: Any, digits: int = 2) -> str:
    try:
        return fmt_signed_currency(to_float(value), digits=digits)
    except Exception:  # noqa: BLE001
        return "—"


def _fmt_pct(value: Any, digits: int = 2) -> str:
    try:
        return fmt_pct(to_float(value), digits=digits)
    except Exception:  # noqa: BLE001
        return "—"


def _render_connection_badge(
    account: Dict[str, Any],
    status: Dict[str, Any],
    error: str | None,
) -> None:
    if error:
        st.markdown(
            "<div style='padding:6px 10px;background:#f2f4f8;border:1px solid #c1c7cd;"
            "border-radius:8px;display:inline-block;font-weight:500;color:#2d3846'>"
            "API STATUS UNKNOWN — account data not yet available."
            "</div>",
            unsafe_allow_html=True,
        )
        return

    if not account:
        st.markdown(
            "<div style='padding:6px 10px;background:#f2f4f8;border:1px solid #c1c7cd;"
            "border-radius:8px;display:inline-block;font-weight:500;color:#2d3846'>"
            "Awaiting broker account data…"
            "</div>",
            unsafe_allow_html=True,
        )
        return

    paper_flag = status.get("paper_mode") if "paper_mode" in status else status.get("paper")
    if paper_flag is None:
        paper_flag = account.get("paper")
    if paper_flag is None:
        paper_flag = True

    if bool(paper_flag):
        st.markdown(
            "<div style='padding:6px 10px;background:#e6fff3;border:1px solid #9de2bf;"
            "border-radius:8px;display:inline-block;font-weight:600;color:#0f5132'>"
            "✅ PAPER MODE — connected to Alpaca paper."
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div style='padding:6px 10px;background:#ffe7cc;border:1px solid #ffbc6b;"
            "border-radius:8px;display:inline-block;font-weight:600;color:#7c3d00'>"
            "⚠️ LIVE MODE — confirm risk controls before trading."
            "</div>",
            unsafe_allow_html=True,
        )


def _trim_orders(raw: Iterable[Dict[str, Any]] | None) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for order in raw or []:
        status = str(order.get("status") or "").strip().lower()
        if status != "filled":
            continue
        rows.append(
            {
                "symbol": order.get("symbol"),
                "side": order.get("side"),
                "qty": order.get("qty") or order.get("quantity"),
                "type": order.get("type"),
                "limit_price": order.get("limit_price") or order.get("limit"),
                "status": order.get("status"),
                "filled_qty": order.get("filled_qty") or order.get("filled_quantity"),
                "submitted_at": order.get("submitted_at") or order.get("created_at"),
            }
        )
    return rows


def _trim_positions(raw: Iterable[Dict[str, Any]] | None) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for pos in raw or []:
        rows.append(
            {
                "symbol": pos.get("symbol") or pos.get("asset_symbol"),
                "qty": pos.get("qty") or pos.get("quantity"),
                "avg_entry_price": pos.get("avg_entry_price") or pos.get("avg_price"),
                "market_value": pos.get("market_value"),
                "unrealized_pl": pos.get("unrealized_pl")
                or pos.get("unrealized_intraday_pl"),
            }
        )
    return rows


def _emit_config_warnings(section: str, payload: Dict[str, Any]) -> None:
    warnings = payload.get("warnings") if isinstance(payload, dict) else None
    if not isinstance(warnings, (list, tuple, set)):
        return
    seen: set[str] = set()
    for message in warnings:
        text = str(message or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        st.warning(f"{section} config warning: {text}")


def _render_status_header(
    status: Dict[str, Any], stream: Dict[str, Any], orchestrator: Dict[str, Any]
) -> None:
    profile_label = "Paper" if status.get("paper_mode", True) else "Live"
    broker_label = str(status.get("broker", "alpaca")).title()
    run_state = str(orchestrator.get("state", "stopped")).title()

    cols = st.columns(4)
    cols[0].metric("Profile", profile_label)
    cols[1].metric("Broker", broker_label)
    cols[2].metric("Run State", run_state)
    cols[3].metric(
        "Kill Switch", "Engaged" if orchestrator.get("kill_switch") else "Standby"
    )

    running = bool(stream.get("running"))
    stream_label = "Running" if running else "Stopped"
    status_pill("Stream", stream_label, variant="positive" if running else "warning")
    if stream.get("source"):
        st.caption(f"Feed source: {stream['source']}")
    if stream.get("last_heartbeat"):
        st.caption(f"Last stream heartbeat: {stream['last_heartbeat']}")
    if stream.get("last_error"):
        st.caption(f"Stream error: {stream['last_error']}")

    if orchestrator.get("last_error"):
        with st.expander("Last orchestrator error", expanded=False):
            st.code(str(orchestrator.get("last_error")))

    if orchestrator.get("last_heartbeat"):
        st.caption(f"Last orchestrator heartbeat: {orchestrator['last_heartbeat']}")
    if orchestrator.get("uptime_secs"):
        uptime_hours = float(orchestrator.get("uptime_secs", 0.0)) / 3600.0
        st.caption(f"Orchestrator uptime: {uptime_hours:.2f}h")


def _render_metrics(
    account: Dict[str, Any], pnl: Dict[str, Any], exposure: Dict[str, Any]
) -> None:
    st.subheader("Telemetry")
    top = st.columns(3)
    top[0].metric("Equity", _fmt_money(account.get("equity")))
    top[1].metric("Cash", _fmt_money(account.get("cash")))
    top[2].metric("Buying Power", _fmt_money(account.get("buying_power")))

    pnl_cols = st.columns(3)
    pnl_cols[0].metric("Realized PnL", _fmt_signed(pnl.get("realized")))
    pnl_cols[1].metric("Unrealized PnL", _fmt_signed(pnl.get("unrealized")))
    pnl_cols[2].metric(
        "Total PnL", _fmt_signed(pnl.get("cumulative") or pnl.get("day_pl"))
    )

    exposure_cols = st.columns(3)
    exposure_cols[0].metric("Net Exposure", _fmt_money(exposure.get("net")))
    exposure_cols[1].metric("Gross Exposure", _fmt_money(exposure.get("gross")))
    symbols = (
        exposure.get("by_symbol") if isinstance(exposure.get("by_symbol"), list) else []
    )
    long_total = 0.0
    short_total = 0.0
    for row in symbols:
        try:
            notional = float(row.get("notional", 0.0))
        except Exception:  # noqa: BLE001 - defensive conversion
            notional = 0.0
        if notional >= 0:
            long_total += notional
        else:
            short_total += notional
    exposure_cols[2].metric(
        "Long / Short", f"{_fmt_money(long_total)} · {_fmt_money(short_total)}"
    )


def _render_algorithm_controls(
    *,
    strategy_cfg: Dict[str, Any],
    orchestrator: Dict[str, Any],
    account: Dict[str, Any],
    api: ApiClient,
) -> None:
    st.subheader("Algorithm Controls")
    mock_mode = bool(account.get("mock_mode"))
    preset_default = (
        strategy_cfg.get("preset") or orchestrator.get("profile") or "balanced"
    )
    try:
        preset_index = DEFAULT_PRESETS.index(preset_default)
    except ValueError:
        preset_index = 1

    with st.form("algorithm_controls"):
        preset = st.selectbox(
            "Run Preset", DEFAULT_PRESETS, index=preset_index, key="cc_run_preset"
        )
        start_col, stop_col, reconcile_col = st.columns(3)
        start_clicked = start_col.form_submit_button("Start Trading")
        stop_clicked = stop_col.form_submit_button("Stop")
        st.caption(
            "Start/stop orchestrator and enable live routing."
            if not mock_mode
            else "Mock mode prevents live orders."
        )

        strategy_flags = strategy_cfg.get("strategies") or {}
        toggles: Dict[str, bool] = {}
        toggle_cols = st.columns(len(STRATEGY_LABELS))
        for idx, (key, label) in enumerate(STRATEGY_LABELS.items()):
            toggles[key] = toggle_cols[idx].checkbox(
                label,
                value=bool(strategy_flags.get(key, True)),
                key=f"cc_strategy_{key}",
            )

        conf_col, ev_col = st.columns(2)
        confidence = conf_col.number_input(
            "Confidence Threshold",
            min_value=0.0,
            max_value=1.0,
            value=float(strategy_cfg.get("confidence_threshold", 0.55) or 0.55),
            step=0.01,
        )
        expected_value = ev_col.number_input(
            "Expected Value Threshold",
            min_value=-5.0,
            max_value=5.0,
            value=float(strategy_cfg.get("expected_value_threshold", 0.0) or 0.0),
            step=0.05,
        )

        universe_default = ",".join(strategy_cfg.get("universe") or [])
        universe_input = st.text_input(
            "Universe",
            value=universe_default,
            placeholder="AAPL, MSFT, NVDA",
            help="Comma separated list of symbols",
            key="cc_universe",
        )

        cooldown, pacing = st.columns(2)
        cooldown_value = cooldown.number_input(
            "Signal Cooldown (sec)",
            min_value=0,
            max_value=3600,
            value=int(strategy_cfg.get("cooldown_sec", 30) or 30),
            step=5,
        )
        pacing_limit = pacing.number_input(
            "Max Signals / Minute",
            min_value=1,
            max_value=240,
            value=int(strategy_cfg.get("pacing_per_minute", 12) or 12),
            step=1,
        )

        dry_run_disabled = not mock_mode
        dry_run_toggle = st.checkbox(
            "Dry Run",
            value=bool(strategy_cfg.get("dry_run")),
            key="cc_dry_run",
            disabled=dry_run_disabled,
            help="Dry run only available in mock mode.",
        )

        update_clicked = st.form_submit_button("Update Strategy Settings")
        reconcile_clicked = reconcile_col.form_submit_button("Sync & Reconcile")

        if start_clicked:
            try:
                result = api.orchestrator_start(preset=preset)
                st.toast(
                    f"Trading started ({result.get('run_id', 'paper')})", icon="✅"
                )
                _schedule_status_poll()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Failed to start trading: {exc}")
        if stop_clicked:
            try:
                api.orchestrator_stop()
                st.toast("Trading stopped", icon="🛑")
                _schedule_status_poll()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Failed to stop trading: {exc}")
        if reconcile_clicked:
            try:
                api.orchestrator_reconcile()
                st.success("Reconcile triggered")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Reconcile failed: {exc}")
        if update_clicked:
            payload = {
                "preset": preset,
                "strategies": toggles,
                "confidence_threshold": confidence,
                "expected_value_threshold": expected_value,
                "universe": [
                    sym.strip().upper()
                    for sym in universe_input.split(",")
                    if sym.strip()
                ],
                "cooldown_sec": cooldown_value,
                "pacing_per_minute": pacing_limit,
                "dry_run": bool(dry_run_toggle),
            }
            try:
                api.strategy_update(payload)
                st.success("Strategy settings updated")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Failed to update strategy settings: {exc}")


def _render_risk_controls(risk_cfg: Dict[str, Any], api: ApiClient) -> None:
    st.subheader("Risk Controls")
    with st.form("risk_controls"):
        daily_loss = st.number_input(
            "Daily Loss Limit",
            min_value=0.0,
            value=float(risk_cfg.get("daily_loss_limit", 2000.0) or 0.0),
            step=100.0,
            key="cc_daily_loss_limit",
        )
        max_positions = st.number_input(
            "Max Positions",
            min_value=0,
            value=int(risk_cfg.get("max_positions", 10) or 0),
            step=1,
            key="cc_max_positions",
        )
        per_symbol_cap = st.number_input(
            "Per-Symbol Notional Cap",
            min_value=0.0,
            value=float(risk_cfg.get("per_symbol_notional", 20000.0) or 0.0),
            step=500.0,
            key="cc_per_symbol_cap",
        )
        portfolio_cap = st.number_input(
            "Portfolio Notional Cap",
            min_value=0.0,
            value=float(risk_cfg.get("portfolio_notional", 100000.0) or 0.0),
            step=1000.0,
            key="cc_portfolio_cap",
        )
        bracket_enabled = st.toggle(
            "Default Bracket Orders",
            value=bool(risk_cfg.get("bracket_enabled", True)),
            key="cc_bracket_enabled",
        )
        submitted = st.form_submit_button("Update Risk Limits")
        if submitted:
            payload = {
                "daily_loss_limit": daily_loss,
                "max_positions": max_positions,
                "per_symbol_notional": per_symbol_cap,
                "portfolio_notional": portfolio_cap,
                "bracket_enabled": bracket_enabled,
            }
            try:
                api.risk_update(payload)
                st.success("Risk controls updated")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Failed to update risk controls: {exc}")


def _render_stream_controls(stream: Dict[str, Any], api: ApiClient) -> None:
    st.subheader("Stream Controls / Status")
    running = bool(stream.get("running"))
    status_label = "Running" if running else "Stopped"
    st.caption(f"Stream status: **{status_label}**")
    cols = st.columns(2)
    if cols[0].button("Start Stream", disabled=running, key="cc_stream_start"):
        try:
            api.stream_start()
            st.toast("Stream start requested", icon="📡")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Failed to start stream: {exc}")
    if cols[1].button("Stop Stream", disabled=not running, key="cc_stream_stop"):
        try:
            api.stream_stop()
            st.toast("Stream stop requested", icon="🛑")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Failed to stop stream: {exc}")


def _render_runbook(orchestrator: Dict[str, Any], api: ApiClient) -> None:
    st.subheader("Runbook / Actions")
    cols = st.columns(4)
    if cols[0].button("Reset Kill Switch", key="cc_reset_kill"):
        try:
            api.risk_reset_kill_switch()
            st.success("Kill switch reset")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Kill switch reset failed: {exc}")
    if cols[1].button("Cancel All", key="cc_cancel_all"):
        try:
            result = api.cancel_all_orders()
            st.success(f"Canceled {result.get('canceled', 0)} orders")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Cancel all failed: {exc}")
    if cols[2].button("Sync & Reconcile", key="cc_sync"):
        try:
            api.orchestrator_reconcile()
            st.success("Reconcile triggered")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Reconcile failed: {exc}")
    if cols[3].button("Run Diagnostics", key="cc_health"):
        try:
            result = api.health()
            st.info(f"Health: {result}")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Diagnostics failed: {exc}")

    if orchestrator.get("kill_switch"):
        st.warning("Kill switch is engaged — trading halted until reset.")


def _render_tables(
    positions: List[Dict[str, Any]],
    orders: List[Dict[str, Any]],
    orders_source: str,
) -> None:
    st.subheader("Open Positions")
    if positions:
        render_table("control_center_positions", positions, page_size=10)
    else:
        st.caption("No open positions.")

    st.subheader("Recent Orders")
    if orders:
        render_table("control_center_orders", orders, page_size=10)
        st.caption(f"Orders from Alpaca via {orders_source}")
    else:
        st.caption("No recent orders.")


def _render_logs(log_lines: List[str], pacing: Dict[str, Any]) -> None:
    st.subheader("Logs & Pacing")
    log_col, pacing_col = st.columns([3, 1])
    if log_lines:
        tail = log_lines[-200:]
        log_col.code("\n".join(str(line) for line in tail))
    else:
        log_col.caption("No recent log events.")

    pacing_col.metric("RPM", pacing.get("rpm", 0.0))
    pacing_col.metric("Max RPM", pacing.get("max_rpm", 0.0))
    pacing_col.metric("Retries", pacing.get("retries", 0))
    pacing_col.metric("Backoff Events", pacing.get("backoff_events", 0))


def _schedule_status_poll(window: float = STATUS_POLL_WINDOW) -> None:
    if _TESTING:
        return
    try:
        st.session_state["__cc_status_poll_until__"] = time.time() + float(window)
    except Exception:
        st.session_state["__cc_status_poll_until__"] = time.time() + STATUS_POLL_WINDOW


def _load_remote_state(api: ApiClient) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    try:
        data["health"] = api.health()
    except Exception as exc:  # noqa: BLE001
        data["health_error"] = str(exc)
        data["health"] = {}
    try:
        data["status"] = api.status()
    except Exception as exc:  # noqa: BLE001
        data["status_error"] = str(exc)
        data["status"] = {}

    try:
        data["account"] = api.account()
    except Exception as exc:  # noqa: BLE001
        data["account_error"] = str(exc)
        data["account"] = {}

    try:
        positions = api.positions()
        data["positions"] = positions if isinstance(positions, list) else []
    except Exception as exc:  # noqa: BLE001
        data["positions_error"] = str(exc)
        data["positions"] = []

    try:
        orders = api.orders(status="closed", limit=50)
        data["orders"] = orders if isinstance(orders, list) else []
    except Exception as exc:  # noqa: BLE001
        data["orders_error"] = str(exc)
        data["orders"] = []

    try:
        data["stream"] = api.stream_status()
    except Exception as exc:  # noqa: BLE001
        data["stream_error"] = str(exc)
        data["stream"] = {"running": False, "source": "mock"}

    try:
        data["orchestrator"] = api.orchestrator_status()
    except Exception as exc:  # noqa: BLE001
        data["orchestrator_error"] = str(exc)
        data["orchestrator"] = {}

    try:
        data["strategy"] = api.strategy_config()
    except Exception as exc:  # noqa: BLE001
        data["strategy_error"] = str(exc)
        data["strategy"] = {}

    try:
        data["risk"] = api.risk_config()
    except Exception as exc:  # noqa: BLE001
        data["risk_error"] = str(exc)
        data["risk"] = {}

    try:
        data["pnl"] = api.pnl_summary()
    except Exception as exc:  # noqa: BLE001
        data["pnl_error"] = str(exc)
        data["pnl"] = {}

    try:
        data["exposure"] = api.exposure()
    except Exception as exc:  # noqa: BLE001
        data["exposure_error"] = str(exc)
        data["exposure"] = {}

    try:
        logs_payload = api.logs_recent(limit=200)
        if isinstance(logs_payload, dict):
            lines = logs_payload.get("lines")
            if not isinstance(lines, list):
                lines = logs_payload.get("entries") or logs_payload.get("events")
            data["logs"] = lines if isinstance(lines, list) else []
        elif isinstance(logs_payload, list):
            data["logs"] = logs_payload
        else:
            data["logs"] = []
    except Exception as exc:  # noqa: BLE001
        data["logs_error"] = str(exc)
        data["logs"] = []
    data.setdefault("pacing", {})

    return data


def render(
    _: BrokerAPI, state: AppSessionState, api_client: ApiClient | None = None
) -> None:
    st.title("Control Center")
    st.markdown('<div data-testid="page-control-center"></div>', unsafe_allow_html=True)
    st.markdown('<div data-testid="control-center-root"></div>', unsafe_allow_html=True)

    api = api_client or ApiClient()
    resolved_base = api.base()
    st.caption(f"Resolved API: {resolved_base}")
    st.sidebar.caption(f"Resolved API: {resolved_base}")
    if not require_backend(api):
        return

    action_cols = st.columns([1, 1, 1])
    with action_cols[0]:
        if st.button("Refresh", key="cc_manual_refresh"):
            st.session_state["__cc_manual_refresh_ts__"] = time.time()
    with action_cols[1]:
        if st.button("Start Orchestrator", key="cc_orchestrator_start_button"):
            try:
                api.orchestrator_start()
            except Exception as exc:  # noqa: BLE001 - surface to UI
                st.warning(f"Start failed: {exc}")
            else:
                _schedule_status_poll()
    with action_cols[2]:
        if st.button("Stop Orchestrator", key="cc_orchestrator_stop_button"):
            try:
                api.orchestrator_stop()
            except Exception as exc:  # noqa: BLE001 - surface to UI
                st.warning(f"Stop failed: {exc}")
            else:
                _schedule_status_poll()

    st.session_state.setdefault("telemetry.autorefresh", False)
    auto_enabled = st.toggle(
        "Auto-refresh telemetry",
        key="telemetry.autorefresh",
        help="Refresh KPIs and tables every few seconds.",
    )

    data = _load_remote_state(api)

    health_snapshot = data.get("health", {}) if isinstance(data, dict) else {}
    status_snapshot = data.get("status", {}) if isinstance(data, dict) else {}
    broker_label = health_snapshot.get("broker", status_snapshot.get("broker", "unknown"))
    dry_run_label = health_snapshot.get("dry_run", status_snapshot.get("dry_run"))
    profile_label = (
        "paper"
        if health_snapshot.get("paper_mode", status_snapshot.get("paper", True))
        else "live"
    )
    st.caption(
        f"Runtime profile={profile_label} · broker={broker_label} · dry_run={dry_run_label}"
    )
    if data.get("health_error"):
        st.warning(f"Health check failed: {data['health_error']}")
    elif data.get("health"):
        st.caption("Backend health: OK")

    _render_connection_badge(
        data.get("account", {}),
        data.get("health", {}),
        data.get("account_error"),
    )

    update_session_state(last_trace_id=data.get("orchestrator", {}).get("last_heartbeat"))

    if data.get("status_error"):
        st.error(f"Backend status unavailable: {data['status_error']}")
    if data.get("account_error"):
        st.warning(f"Alpaca account unavailable: {data['account_error']}")
    if data.get("positions_error"):
        st.warning(f"Positions unavailable: {data['positions_error']}")
    if data.get("orders_error"):
        st.warning(f"Orders unavailable: {data['orders_error']}")
    if data.get("stream_error"):
        st.warning(f"Stream status unavailable: {data['stream_error']}")
    if data.get("strategy_error"):
        st.warning(f"Strategy configuration unavailable: {data['strategy_error']}")
    if data.get("risk_error"):
        st.warning(f"Risk configuration unavailable: {data['risk_error']}")
    if data.get("pnl_error"):
        st.warning(f"PnL summary unavailable: {data['pnl_error']}")
    if data.get("exposure_error"):
        st.warning(f"Exposure telemetry unavailable: {data['exposure_error']}")
    if data.get("logs_error"):
        st.warning(f"Log tail unavailable: {data['logs_error']}")

    _emit_config_warnings("Orchestrator", data.get("orchestrator", {}))
    _emit_config_warnings("Strategy", data.get("strategy", {}))
    _emit_config_warnings("Risk", data.get("risk", {}))

    _render_status_header(
        data.get("health", {}), data.get("stream", {}), data.get("orchestrator", {})
    )
    _render_metrics(
        data.get("account", {}), data.get("pnl", {}), data.get("exposure", {})
    )
    _render_algorithm_controls(
        strategy_cfg=data.get("strategy", {}),
        orchestrator=data.get("orchestrator", {}),
        account=data.get("account", {}),
        api=api,
    )
    _render_risk_controls(data.get("risk", {}), api)
    _render_stream_controls(data.get("stream", {}), api)
    _render_runbook(data.get("orchestrator", {}), api)

    positions = _trim_positions(data.get("positions"))
    orders = _trim_orders(data.get("orders"))
    _render_tables(positions, orders, api.base())
    _render_logs(data.get("logs", []), data.get("pacing", {}))

    now_ts = time.time()
    poll_until = st.session_state.get("__cc_status_poll_until__", 0.0)
    if poll_until and now_ts >= poll_until:
        st.session_state.pop("__cc_status_poll_until__", None)

    if auto_enabled:
        st_autorefresh(
            interval=int(REFRESH_INTERVAL_SEC * 1000),
            key="telemetry.autorefresh.tick",
        )

    if not _TESTING:
        next_poll = st.session_state.get("__cc_status_poll_until__", 0.0)
        if next_poll and next_poll > now_ts:
            st_autorefresh(
                interval=int(STATUS_POLL_INTERVAL * 1000),
                key="telemetry.status.poll",
            )
