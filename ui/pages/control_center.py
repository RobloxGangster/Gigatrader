from __future__ import annotations

import os
import sys
import time
import signal
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import requests
import streamlit as st

# psutil is optional. If it's not available, we'll degrade gracefully.
try:
    import psutil  # type: ignore
except Exception:
    psutil = None

from ui.components.badges import status_pill
from ui.components.tables import render_table
from ui.lib.api_client import ApiClient
from ui.lib.st_compat import auto_refresh
from ui.state import AppSessionState, update_session_state
from ui.utils.format import fmt_currency, fmt_pct, fmt_signed_currency
from ui.utils.num import to_float
from ui.services.backend import BrokerAPI
from ui.services.healthcheck import probe_backend

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
BACKEND_URL = "http://127.0.0.1:8000"

_SESSION_PID_KEY = "backend.pid"

ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = ROOT / "logs"
PID_FILE = LOG_DIR / "backend.pid"
EXIT_FILE = LOG_DIR / "backend.exitcode"
AUTOSTART_LOG = LOG_DIR / "backend_autostart.log"
BACKEND_ERR_LOG = LOG_DIR / "backend.err.log"
BACKEND_OUT_LOG = LOG_DIR / "backend.out.log"


def _pid_is_alive(pid: Optional[int]) -> bool:
    """
    Return True if a process with this PID still appears to be running.
    Prefer psutil if available. Fallback to os.kill semantics.
    """
    if not pid:
        return False

    # psutil path first (most reliable cross-platform)
    if psutil is not None:
        try:
            proc = psutil.Process(pid)
            if not proc.is_running():
                return False
            # Avoid treating zombies as alive on POSIX
            if getattr(psutil, "STATUS_ZOMBIE", None) and proc.status() == psutil.STATUS_ZOMBIE:
                return False
            return True
        except Exception:
            return False

    # no psutil? use os.kill probe
    try:
        # os.kill(pid, 0) => check signal delivery without killing (POSIX);
        # on Windows this raises OSError for dead processes.
        os.kill(pid, 0)
        return True
    except PermissionError:
        # access denied still means "something is there"
        return True
    except Exception:
        return False


def _read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return default


def _tail_lines(txt: str, n: int = 200) -> str:
    lines = txt.splitlines()
    if not lines:
        return txt
    return "\n".join(lines[-n:])


def _get_pid_status() -> Tuple[Optional[int], bool, Optional[str], str]:
    pid: Optional[int] = None
    if PID_FILE.exists():
        try:
            raw = PID_FILE.read_text(encoding="utf-8").strip()
            if raw:
                pid = int(raw)
        except Exception:
            pid = None

    crashed = False
    exit_code: Optional[str] = None
    if EXIT_FILE.exists():
        crashed = True
        try:
            exit_code = EXIT_FILE.read_text(encoding="utf-8").strip() or None
        except Exception:
            exit_code = "?"

    alive = False
    if pid and not crashed:
        alive = _pid_is_alive(pid)

    status_label = "unknown"
    if alive and pid:
        status_label = f"running (PID {pid})"
    elif crashed and pid:
        status_label = f"crashed (PID {pid}, exit {exit_code})"
    elif crashed and not pid:
        status_label = f"crashed (PID ?, exit {exit_code})"
    elif pid:
        status_label = f"not running (stale PID {pid})"
    else:
        status_label = "not running"

    return pid, crashed, exit_code, status_label


def render_backend_process_panel() -> None:
    st.subheader("Backend Process")

    pid, crashed, exit_code, status_label = _get_pid_status()
    st.text(f"Status: {status_label}")
    st.text(f"PID file contents: {pid if pid is not None else '(none)'}")
    if crashed:
        st.text(f"Exit code: {exit_code if exit_code is not None else '(unknown)'}")

    st.caption("backend_autostart.log tail:")
    auto_tail = _tail_lines(
        _read_text(AUTOSTART_LOG, default="(no backend_autostart.log found)"),
        n=200,
    )
    st.code(auto_tail or "(empty)", language="text")

    st.caption("backend.err.log tail (uvicorn stderr):")
    err_tail = _tail_lines(
        _read_text(BACKEND_ERR_LOG, default="(no backend.err.log yet)"),
        n=200,
    )
    st.code(err_tail or "(empty)", language="text")

    with st.expander("backend.out.log tail (uvicorn stdout)", expanded=False):
        out_tail = _tail_lines(
            _read_text(BACKEND_OUT_LOG, default="(no backend.out.log yet)"),
            n=200,
        )
        st.code(out_tail or "(empty)", language="text")


def _spawn_backend_if_needed() -> int:
    """
    Ensure we have one backend launcher process running.
    If we already have a live PID in st.session_state[_SESSION_PID_KEY], reuse it.
    Otherwise spawn scripts/start_backend.py in a detached process
    using this same Python interpreter.
    Return the PID (either reused or new).
    """
    existing_pid = st.session_state.get(_SESSION_PID_KEY)
    if existing_pid and _pid_is_alive(existing_pid):
        return existing_pid

    # PID missing or dead → spawn new one.
    os.makedirs("logs", exist_ok=True)

    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    proc = subprocess.Popen(
        [sys.executable, "-u", "scripts/start_backend.py"],
        cwd=os.getcwd(),
        env=os.environ.copy(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )

    new_pid = proc.pid
    st.session_state[_SESSION_PID_KEY] = new_pid

    # small grace to let python import backend.api, write first log lines, etc.
    time.sleep(0.25)

    return new_pid


def _stop_backend() -> None:
    """
    Attempt to kill the backend process recorded in session_state.
    Clear the PID afterwards.
    """
    pid = st.session_state.get(_SESSION_PID_KEY)
    if not pid:
        return

    # try best-effort graceful kill
    try:
        if psutil is not None:
            try:
                p = psutil.Process(pid)
                p.terminate()
            except Exception:
                pass
        else:
            # portable-ish fallback
            if os.name == "nt":
                # Windows: TerminateProcess via taskkill is simplest
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)
    except Exception:
        pass

    # give it a moment to die
    time.sleep(0.25)

    st.session_state[_SESSION_PID_KEY] = None


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
    broker_status: Mapping[str, Any] | None,
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

    broker_impl = "unknown"
    broker_profile = "paper" if paper_flag else "live"
    dry_run_flag: bool | None = None
    if isinstance(broker_status, Mapping):
        broker_impl = str(broker_status.get("impl", broker_impl))
        profile_override = broker_status.get("profile")
        if isinstance(profile_override, str) and profile_override:
            broker_profile = profile_override
        dry_run_raw = broker_status.get("dry_run")
        if dry_run_raw is not None:
            dry_run_flag = bool(dry_run_raw)
    if dry_run_flag is None:
        dry_run_flag = bool(status.get("dry_run"))

    impl_lower = broker_impl.lower()
    if impl_lower.startswith("mock") or bool(status.get("mock_mode")):
        st.warning("MOCK MODE — simulated broker (no live orders).")
        st.caption(
            "Execution adapter: Mock broker (orders remain local to this session)."
        )
    else:
        profile_label = "paper" if broker_profile.lower() != "live" else "live"
        st.success(
            f"{profile_label.upper()} MODE — connected to Alpaca {profile_label}."
        )
        st.caption(
            f"Execution adapter: {broker_impl} (profile={profile_label}, dry_run={dry_run_flag})."
        )

    if dry_run_flag:
        st.warning("dry_run is ON — orders will NOT be sent to Alpaca.")


def _trim_orders(raw: Iterable[Dict[str, Any]] | None) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for order in raw or []:
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
    health: Dict[str, Any],
    stream: Dict[str, Any],
    orchestrator: Dict[str, Any],
    orchestrator_debug: Dict[str, Any],
    runtime_flags: Dict[str, Any],
    execution_tail: Dict[str, Any],
    *,
    backend_up: bool,
    env_profile: str,
    env_broker: str,
) -> None:
    orch_status = orchestrator_debug.get("status", orchestrator)
    if not isinstance(orch_status, dict):
        orch_status = orchestrator

    profile_label = env_profile.title()
    broker_label = str(env_broker or "unknown").title()
    run_state = "Stopped"
    stream_source = "offline"
    kill_switch_label = "Unknown"
    kill_switch_engaged = False

    if backend_up:
        runtime_profile = runtime_flags.get("profile") if isinstance(runtime_flags, dict) else None
        profile_value = runtime_profile or health.get("profile") or orch_status.get("profile")
        if isinstance(profile_value, str) and profile_value:
            profile_label = ("Live" if profile_value.lower() == "live" else "Paper")
        runtime_broker = runtime_flags.get("broker") if isinstance(runtime_flags, dict) else None
        broker_value = runtime_broker or health.get("broker") or orch_status.get("broker_impl")
        if broker_value is not None:
            broker_label = str(broker_value).title()
        run_state = str(
            health.get("orchestrator_state") or orch_status.get("state") or "Unknown"
        )
        stream_source = str(health.get("stream_source") or stream.get("source") or "unknown")
        kill_switch_label = (
            health.get("kill_switch")
            or orch_status.get("kill_switch")
            or ("Engaged" if orchestrator.get("kill_switch") else "Standby")
        )
        kill_switch_engaged = bool(
            orch_status.get("kill_switch_engaged", orchestrator.get("kill_switch"))
        )

    cols = st.columns(5)
    cols[0].metric("Profile", profile_label)
    cols[1].metric("Broker", broker_label)
    cols[2].metric("Run State", run_state)
    cols[3].metric("Stream Source", stream_source)
    cols[4].metric("Kill Switch", kill_switch_label)

    if not backend_up:
        status_pill("Stream", "Offline", variant="warning")
        status_pill("Execution", "Offline", variant="warning")
        st.caption("Execution adapter offline while backend is stopped.")
        return

    stream_details = {}
    details_raw = health.get("stream_details")
    if isinstance(details_raw, dict):
        stream_details = details_raw
    elif isinstance(stream, dict):
        stream_details = stream
    stream_source_detail = (
        health.get("stream_source")
        or stream_details.get("source")
        or stream.get("source")
    )
    if isinstance(runtime_flags, dict) and runtime_flags.get("market_data_source"):
        stream_source_detail = runtime_flags.get("market_data_source")
    running = bool(stream_details.get("running", stream.get("running")))
    stream_label = "Running" if running else "Stopped"
    status_pill("Stream", stream_label, variant="positive" if running else "warning")
    if stream_source_detail:
        st.caption(f"Market data feed: {stream_source_detail}")
    heartbeat = (
        stream_details.get("last_heartbeat")
        or health.get("stream_last_heartbeat")
        or stream.get("last_heartbeat")
    )
    if heartbeat:
        st.caption(f"Last stream heartbeat: {heartbeat}")
    if stream_details.get("last_error"):
        st.caption(f"Stream error: {stream_details['last_error']}")

    if orch_status.get("last_error"):
        with st.expander("Last orchestrator error", expanded=False):
            st.code(str(orch_status.get("last_error")))

    if orch_status.get("last_heartbeat"):
        st.caption(f"Last orchestrator heartbeat: {orch_status['last_heartbeat']}")
    uptime = orch_status.get("uptime")
    if uptime:
        st.caption(f"Orchestrator uptime: {uptime}")

    runtime_dry_run = False
    runtime_mock = False
    if isinstance(runtime_flags, dict):
        runtime_dry_run = bool(runtime_flags.get("dry_run"))
        runtime_mock = bool(runtime_flags.get("mock_mode"))

    last_attempt = orchestrator_debug.get("last_order_attempt", {})
    if last_attempt.get("ts"):
        symbol = last_attempt.get("symbol") or "—"
        side = last_attempt.get("side") or "—"
        qty = last_attempt.get("qty")
        qty_label = qty if qty is not None else "—"
        status_parts = []
        status_parts.append("sent" if last_attempt.get("sent") else "skipped")
        status_parts.append("accepted" if last_attempt.get("accepted") else "not accepted")
        if last_attempt.get("reason"):
            status_parts.append(str(last_attempt["reason"]))
        broker_impl = last_attempt.get("broker_impl") or broker_label
        st.caption(
            f"Last order attempt ({last_attempt['ts']}): "
            f"{symbol} {side} × {qty_label} — {' / '.join(status_parts)} via {broker_impl}."
        )

    exec_variant = "positive"
    exec_label = "Active"
    exec_caption = f"Execution adapter: {broker_label}"
    if runtime_mock:
        exec_variant = "warning"
        exec_label = "Mock"
        exec_caption += " (mock broker)"
    elif runtime_dry_run:
        exec_variant = "warning"
        exec_label = "Dry Run"
        exec_caption += " (dry_run=true)"
    status_pill("Execution", exec_label, variant=exec_variant)
    st.caption(exec_caption)
    if runtime_dry_run:
        st.warning("dry_run is ON — orders will NOT be sent to Alpaca.")

    tail_lines = []
    if isinstance(execution_tail, dict):
        tail_lines = execution_tail.get("lines") or []
    tail_preview = [str(line) for line in tail_lines[-3:]]
    if tail_preview:
        with st.expander("Execution debug (tail)", expanded=False):
            st.code("\n".join(tail_preview) or "No execution debug logs yet.")

    if kill_switch_engaged:
        st.warning("KILL SWITCH ACTIVE — trading disabled until reset.")


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
        start_label = "Start Paper" if mock_mode else "Start Trading"
        preset = st.selectbox(
            "Run Preset", DEFAULT_PRESETS, index=preset_index, key="cc_run_preset"
        )
        start_col, stop_col, reconcile_col = st.columns(3)
        start_clicked = start_col.form_submit_button(start_label)
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
    st.subheader("Recent Activity")
    cols = st.columns(2)
    with cols[0]:
        st.markdown("##### Open Positions")
        if positions:
            render_table("control_center_positions", positions, page_size=10)
        else:
            st.caption("No open positions.")
    with cols[1]:
        st.markdown("##### Recent Orders")
        if orders:
            render_table("control_center_orders", orders, page_size=10)
            st.caption(f"Orders from broker via {orders_source}")
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


def _load_remote_state(
    api: ApiClient, backend_up: bool, health_payload: Mapping[str, Any] | None
) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    if isinstance(health_payload, Mapping):
        data["health"] = dict(health_payload)
    else:
        data["health"] = {}

    if not backend_up:
        data["health_unreachable"] = True
        return data

    try:
        data["status"] = api.status()
    except Exception as exc:  # noqa: BLE001
        data["status_error"] = str(exc)
        data["status"] = {}

    try:
        data["broker"] = api.broker_status()
    except Exception as exc:  # noqa: BLE001
        data["broker_error"] = str(exc)
        data["broker"] = {}

    try:
        data["account"] = api.account()
    except Exception as exc:  # noqa: BLE001
        data["account_error"] = str(exc)
        data["account"] = {}

    health = data.get("health")
    if isinstance(health, dict) and health.get("mock_mode"):
        account_snapshot = data.setdefault("account", {})
        if isinstance(account_snapshot, dict):
            account_snapshot.setdefault("mock_mode", True)
        st.session_state["__mock_mode__"] = True

    try:
        positions = api.positions()
        data["positions"] = positions if isinstance(positions, list) else []
    except requests.HTTPError as exc:
        status = exc.response.status_code if getattr(exc, "response", None) else None
        data["positions_error"] = str(exc)
        if status in {401, 403}:
            data["positions_auth_error"] = True
        data["positions"] = []
    except Exception as exc:  # noqa: BLE001
        data["positions_error"] = str(exc)
        data["positions"] = []

    try:
        orders = api.orders(status="closed", limit=50)
        data["orders"] = orders if isinstance(orders, list) else []
    except requests.HTTPError as exc:
        status = exc.response.status_code if getattr(exc, "response", None) else None
        data["orders_error"] = str(exc)
        if status in {401, 403}:
            data["orders_auth_error"] = True
        data["orders"] = []
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
        data["orchestrator_debug"] = api.orchestrator_debug()
    except Exception as exc:  # noqa: BLE001
        data["orchestrator_debug_error"] = str(exc)
        data["orchestrator_debug"] = {}

    try:
        data["runtime_flags"] = api.debug_runtime()
    except Exception as exc:  # noqa: BLE001
        data["runtime_flags_error"] = str(exc)
        data["runtime_flags"] = {}

    try:
        data["execution_tail"] = api.execution_tail(limit=100)
    except Exception as exc:  # noqa: BLE001
        data["execution_tail_error"] = str(exc)
        data["execution_tail"] = {"lines": []}

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
    if st.button("Refresh", key="cc_manual_refresh"):
        st.session_state["__cc_manual_refresh_ts__"] = time.time()

    col_start, col_stop = st.columns([1, 1])
    with col_start:
        if st.button("Start Trading System"):
            _spawn_backend_if_needed()

    with col_stop:
        if st.button("Stop Trading System"):
            _stop_backend()

    # Sync session_state pid with reality
    pid = st.session_state.get(_SESSION_PID_KEY)
    if pid and not _pid_is_alive(pid):
        st.session_state.pop(_SESSION_PID_KEY, None)

    render_backend_process_panel()

    # Probe backend: we require /health AND /broker/status to both succeed.
    is_up, health_info, err_msg = probe_backend(BACKEND_URL, timeout_sec=3.0)

    if not is_up:
        # backend either isn't running, or it crashed immediately, or it's missing keys, etc.
        st.error(
            "Backend is NOT reachable on 127.0.0.1:8000.\n\n"
            "Orders cannot be submitted, Alpaca account cannot be queried."
        )

        # Show captured error from the probe
        if err_msg:
            st.warning(f"Health probe error: {err_msg}")

        st.stop()

    st.session_state["backend.health"] = health_info

    st.session_state.setdefault("telemetry.autorefresh", False)
    auto_enabled = st.toggle(
        "Auto-refresh telemetry",
        key="telemetry.autorefresh",
        help="Refresh KPIs and tables every few seconds.",
    )

    profile = health_info.get("profile", "unknown")
    broker_name = health_info.get("broker", "unknown")
    run_state = health_info.get("orchestrator_state", "unknown")
    stream_src = health_info.get("stream_source", "unknown")
    kill_switch = health_info.get("kill_switch", "unknown")

    if "mock" in str(stream_src).lower():
        st.warning("MOCK MODE — backend running in mock mode. Live orders will NOT be sent.")
    else:
        st.success("PAPER MODE — connected to Alpaca paper.")

    st.write("Profile:", profile)
    st.write("Broker:", broker_name)
    st.write("Run State:", run_state)
    st.write("Stream Source:", stream_src)
    st.write("Kill Switch:", kill_switch)
    st.write(
        "Runtime mode:",
        f"{broker_name} adapter "
        f"(profile={profile}, dry_run={health_info.get('dry_run', 'unknown')})",
    )

    # From here on, NOW it's valid to call /broker/positions, /orders, /pnl/summary, etc.
    # Those calls should NOT raise WinError 10061 anymore because the backend is confirmed alive.

    health_payload = health_info

    backend_running = True

    data = _load_remote_state(api, backend_running, health_payload)
    backend_up = backend_running

    health_snapshot = data.get("health", {}) if isinstance(data, dict) else {}
    status_snapshot = data.get("status", {}) if isinstance(data, dict) else {}
    runtime_snapshot = data.get("runtime_flags", {}) if isinstance(data, dict) else {}
    broker_snapshot = data.get("broker", {}) if isinstance(data, dict) else {}

    truthy = {"1", "true", "yes", "on"}
    env_profile_raw = os.environ.get("PROFILE") or os.environ.get("TRADING_MODE") or "paper"
    env_profile = "live" if str(env_profile_raw).lower() == "live" else "paper"
    env_broker = os.environ.get("BROKER") or os.environ.get("TRADING_BROKER") or "alpaca"
    env_dry_run_flag = str(os.environ.get("DRY_RUN") or "").strip().lower() in truthy
    env_mock_flag = (
        str(os.environ.get("MOCK_MODE") or os.environ.get("MOCK_MARKET") or "")
        .strip()
        .lower()
        in truthy
    )

    broker_label: str = str(env_broker)
    profile_label: str = str(env_profile)
    dry_run_label: bool = bool(env_dry_run_flag)
    mock_mode_flag: bool = bool(env_mock_flag)

    if backend_up and isinstance(status_snapshot, Mapping):
        broker_label = str(status_snapshot.get("broker", broker_label))
        dry_run_label = bool(status_snapshot.get("dry_run", dry_run_label))
        profile_candidate = status_snapshot.get("profile")
        if isinstance(profile_candidate, str) and profile_candidate:
            profile_label = profile_candidate

    if backend_up and isinstance(runtime_snapshot, Mapping):
        broker_label = str(runtime_snapshot.get("broker", broker_label))
        dry_run_label = bool(runtime_snapshot.get("dry_run", dry_run_label))
        profile_candidate = runtime_snapshot.get("profile")
        if isinstance(profile_candidate, str) and profile_candidate:
            profile_label = profile_candidate
        if "mock_mode" in runtime_snapshot:
            mock_mode_flag = bool(runtime_snapshot.get("mock_mode"))

    if backend_up and isinstance(health_snapshot, Mapping):
        broker_label = str(health_snapshot.get("broker", broker_label))
        if "dry_run" in health_snapshot:
            dry_run_label = bool(health_snapshot.get("dry_run"))
        paper_mode = health_snapshot.get("paper_mode")
        if paper_mode is not None:
            profile_label = "paper" if bool(paper_mode) else "live"
        profile_candidate = health_snapshot.get("profile")
        if isinstance(profile_candidate, str) and profile_candidate:
            profile_label = profile_candidate
        if "mock_mode" in health_snapshot:
            mock_mode_flag = bool(health_snapshot.get("mock_mode"))

    if backend_up and isinstance(broker_snapshot, Mapping):
        broker_label = str(broker_snapshot.get("impl", broker_label))
        if "dry_run" in broker_snapshot:
            dry_run_label = bool(broker_snapshot.get("dry_run"))
        profile_candidate = broker_snapshot.get("profile")
        if isinstance(profile_candidate, str) and profile_candidate:
            profile_label = profile_candidate

    if mock_mode_flag:
        st.sidebar.info("Mock mode enabled")

    st.caption(
        f"Runtime mode: {broker_label} (profile={profile_label}, dry_run={dry_run_label})"
    )

    if data.get("runtime_flags_error"):
        st.warning(f"Runtime flags unavailable: {data['runtime_flags_error']}")
    if data.get("broker_error"):
        st.warning(f"Broker status unavailable: {data['broker_error']}")

    _render_connection_badge(
        data.get("account", {}),
        data.get("health", {}),
        data.get("broker", {}),
        data.get("account_error"),
    )

    if data.get("orders_auth_error") or data.get("positions_auth_error"):
        st.error(
            "Broker rejected credentials. Check ALPACA_KEY_ID / ALPACA_SECRET_KEY / ALPACA_USE_PAPER in .env."
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
    if data.get("orchestrator_debug_error"):
        st.warning(
            f"Orchestrator debug unavailable: {data['orchestrator_debug_error']}"
        )
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
    if data.get("execution_tail_error"):
        st.warning(f"Execution debug unavailable: {data['execution_tail_error']}")

    _emit_config_warnings("Orchestrator", data.get("orchestrator", {}))
    _emit_config_warnings("Strategy", data.get("strategy", {}))
    _emit_config_warnings("Risk", data.get("risk", {}))

    _render_status_header(
        data.get("health", {}),
        data.get("stream", {}),
        data.get("orchestrator", {}),
        data.get("orchestrator_debug", {}),
        data.get("runtime_flags", {}),
        data.get("execution_tail", {}),
        backend_up=backend_up,
        env_profile=env_profile,
        env_broker=env_broker,
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
        auto_refresh(interval_ms=int(REFRESH_INTERVAL_SEC * 1000), key="telemetry.autorefresh.tick")

    if not _TESTING:
        next_poll = st.session_state.get("__cc_status_poll_until__", 0.0)
        if next_poll and next_poll > now_ts:
            auto_refresh(interval_ms=int(STATUS_POLL_INTERVAL * 1000), key="telemetry.status.poll")
