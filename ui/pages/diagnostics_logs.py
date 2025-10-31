from __future__ import annotations

import json
import os
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd
import requests
import streamlit as st

from ui.lib.api_client import ApiClient, build_url
from ui.lib.nav import NAV_ITEMS
from ui.lib.ui_compat import safe_rerun

STATE_KEY = "__diagnostics_state__"
DEFAULT_LINES = 200
REFRESH_INTERVAL_MS = 5_000
_DEFAULT_SLUG = "diagnostics"


def _read_query_slug() -> str:
    try:
        params = dict(st.query_params)  # type: ignore[arg-type]
    except Exception:  # pragma: no cover - Streamlit < 1.30 fallback
        raw = st.experimental_get_query_params()
        params = {k: v[0] if isinstance(v, list) and v else v for k, v in raw.items()}
    slug = str(params.get("page", _DEFAULT_SLUG) or _DEFAULT_SLUG).strip().lower()
    return slug or _DEFAULT_SLUG


def _set_query_slug(slug: str) -> None:
    try:
        st.query_params["page"] = slug
    except Exception:  # pragma: no cover - legacy fallback
        st.experimental_set_query_params(page=slug)


def _fmt_money(value: Any) -> str:
    try:
        return f"${float(value):,.2f}"
    except Exception:  # noqa: BLE001 - formatting guard
        return "—"


def _fmt_signed(value: Any) -> str:
    try:
        return f"{float(value):+,.2f}"
    except Exception:  # noqa: BLE001 - formatting guard
        return "—"


def _iter_fixture_files(fixtures_dir: Path) -> Iterable[Path]:
    if not fixtures_dir.exists():
        return []
    return [path for path in fixtures_dir.iterdir() if path.is_file()]


def _create_repro_bundle() -> Path | None:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target_dir = Path("repros")
    target_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = target_dir / f"repro_{timestamp}.zip"

    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in ("config.yaml", "config.example.yaml", "RISK_PRESETS.md"):
            candidate = Path(name)
            if candidate.exists() and candidate.is_file():
                bundle.write(candidate, arcname=candidate.name)

        fixtures_dir = Path("fixtures")
        for fixture in _iter_fixture_files(fixtures_dir):
            bundle.write(fixture, arcname=f"fixtures/{fixture.name}")

        logs_dir = Path("logs")
        if logs_dir.exists():
            for log_file in logs_dir.rglob("*"):
                if log_file.is_file():
                    try:
                        arcname = log_file.relative_to(Path.cwd())
                    except ValueError:
                        arcname = log_file.name
                    bundle.write(log_file, arcname=str(arcname))

    return bundle_path


def _get_state() -> Dict[str, Any]:
    return st.session_state.setdefault(
        STATE_KEY,
        {
            "health": {},
            "health_error": None,
            "pacing": {},
            "pacing_error": None,
            "logs_error": None,
            "log_entries": [],
            "limit": DEFAULT_LINES,
            "filter": "",
            "auto_enabled": False,
            "last_refresh_token": 0,
            "last_diagnostics_at": None,
            "last_logs_at": None,
            "execution_tail": {"lines": []},
            "execution_error": None,
            "backend_up": False,
            "telemetry": {},
            "telemetry_error": None,
            "telemetry_trades": [],
            "telemetry_trades_error": None,
        },
    )


def render() -> None:
    st.header("Diagnostics / Logs")
    st.caption("Backend health, pacing, and recent logs. Export and refresh controls below.")

    nav_labels = [item["label"] for item in NAV_ITEMS]
    nav_lookup = {item["label"]: item["slug"] for item in NAV_ITEMS}
    current_slug = _read_query_slug()
    current_label = next(
        (label for label, slug in nav_lookup.items() if slug == current_slug),
        "Diagnostics / Logs",
    )
    if current_label not in nav_labels:
        nav_labels.insert(0, current_label)
        nav_lookup[current_label] = current_slug

    try:
        current_index = nav_labels.index(current_label)
    except ValueError:
        current_index = 0

    selection = st.selectbox(
        "Navigate",
        nav_labels,
        index=current_index,
        help="Jump between Gigatrader pages.",
    )
    selected_slug = nav_lookup.get(selection, _DEFAULT_SLUG)
    if selected_slug != current_slug:
        _set_query_slug(selected_slug)
        safe_rerun()
        return

    client = ApiClient()
    state = _get_state()

    if st.button("Create Repro Bundle", type="primary"):
        bundle = _create_repro_bundle()
        if bundle is not None:
            st.success(f"Repro bundle created: {bundle}")
        else:
            st.warning("Unable to create repro bundle.")

    controls = st.columns([1, 1, 2])
    with controls[0]:
        run_clicked = st.button(
            "Run Diagnostics",
            type="primary",
            help="Fetch /health, /pacing, and the latest log tail.",
        )
    with controls[1]:
        limit = int(
            st.number_input(
                "Lines",
                min_value=50,
                max_value=5000,
                value=int(state.get("limit", DEFAULT_LINES)),
                step=50,
            )
        )
    with controls[2]:
        filter_text = st.text_input(
            "Filter (contains)",
            value=str(state.get("filter", "")),
            placeholder="error, worker, order id …",
        )

    state["filter"] = filter_text

    state_limit = state.get("limit", DEFAULT_LINES)
    if state_limit != limit:
        state["limit"] = limit
        if state.get("log_entries"):
            _fetch_logs(client, state, limit)

    backend_up = False
    health_payload: Dict[str, Any] | None = None
    try:
        resp = requests.get("http://127.0.0.1:8000/health", timeout=1.5)
    except requests.RequestException:
        resp = None
    if resp is not None and resp.status_code == 200:
        try:
            parsed = resp.json()
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            backend_up = True
            health_payload = parsed

    state["backend_up"] = backend_up
    if backend_up and isinstance(health_payload, dict):
        state["health"] = health_payload
        state["health_error"] = None
    else:
        state["health"] = {}
        state["health_error"] = {
            "path": "/health",
            "error": "Backend is NOT reachable at http://127.0.0.1:8000.",
        }
        state["pacing"] = {}
        state["pacing_error"] = None
        state["log_entries"] = []
        state["logs_error"] = None
        state["execution_tail"] = {"lines": []}
        state["execution_error"] = None

    if backend_up and not state.get("telemetry"):
        _fetch_telemetry(client, state)

    interval_sec = REFRESH_INTERVAL_MS / 1000.0
    now = time.time()
    if run_clicked and backend_up:
        _run_full_diagnostics(client, state, limit)
    elif backend_up and state.get("auto_enabled"):
        last_auto = float(state.get("last_auto_refresh", 0.0) or 0.0)
        if now - last_auto >= interval_sec:
            state["last_auto_refresh"] = now
            _fetch_logs(client, state, limit)
            _fetch_execution_tail(client, state, limit)
            _fetch_telemetry(client, state)

    health_error = state.get("health_error")
    pacing_error = state.get("pacing_error")
    logs_error = state.get("logs_error")
    execution_error = state.get("execution_error")

    if not backend_up:
        st.error(
            "Backend is NOT reachable at http://127.0.0.1:8000. Trading system is NOT running."
        )
    elif health_error:
        _render_failure(health_error, client)
    if pacing_error:
        _render_failure(pacing_error, client)
    if logs_error:
        _render_failure(logs_error, client)
    if execution_error:
        _render_failure(execution_error, client)

    health = state.get("health", {})
    pacing = state.get("pacing", {}) if isinstance(state.get("pacing"), dict) else {}

    _render_health_summary(health, pacing)
    _render_telemetry_panel(state)
    st.subheader("Logs & Pacing")
    st.json(pacing or {"message": "No pacing telemetry"}, expanded=False)

    entries: List[Dict[str, Any]] = state.get("log_entries", [])
    filtered_entries = _apply_filter(entries, filter_text)

    log_lines = [entry["text"] for entry in filtered_entries]
    table_rows = [entry["row"] for entry in filtered_entries if entry.get("row")]

    export_text = "\n".join(log_lines)
    st.subheader("Logs")

    st.download_button(
        "Export logs (text)",
        data=export_text.encode("utf-8"),
        file_name=_export_filename(),
        mime="text/plain",
    )

    archive_bytes = b""
    archive_error = None
    if backend_up:
        try:
            archive_bytes = client.logs_archive()
        except Exception as exc:  # noqa: BLE001 - surface fetch errors
            archive_error = str(exc)
    if archive_bytes:
        st.download_button(
            "Download log archive (.zip)",
            data=archive_bytes,
            file_name="diagnostics-logs.zip",
            mime="application/zip",
        )
    elif archive_error:
        st.info(f"Log archive unavailable: {archive_error}")

    if table_rows:
        df = pd.DataFrame(table_rows, columns=["time", "level", "worker", "msg"])
        st.dataframe(df, use_container_width=True, height=360)
    else:
        st.info("No structured log entries available.")

    st.code(export_text or "No log lines fetched yet.", language="text")

    exec_tail = state.get("execution_tail", {})
    exec_lines = []
    if isinstance(exec_tail, dict):
        exec_lines = exec_tail.get("lines") or []
    st.subheader("Execution Debug Tail")
    if exec_lines:
        st.code("\n".join(str(line) for line in exec_lines), language="text")
    else:
        st.info("No execution debug lines fetched yet.")

    diagnostics_ts = state.get("last_diagnostics_at")
    logs_ts = state.get("last_logs_at")
    status_parts = []
    if diagnostics_ts:
        status_parts.append(f"Diagnostics @ {diagnostics_ts}")
    if logs_ts and logs_ts != diagnostics_ts:
        status_parts.append(f"Logs updated @ {logs_ts}")
    status_parts.append(f"Endpoint: {client.base()}")
    st.caption(" · ".join(status_parts))


def _render_failure(payload: Dict[str, Any], client: ApiClient) -> None:
    path = payload.get("path", "")
    message = payload.get("error") or payload.get("message") or payload
    url = build_url(path) if path else client.base()
    st.info(f"{url}\n{message}")


def _render_health_summary(health: Dict[str, Any], pacing: Dict[str, Any]) -> None:
    health_status = str(health.get("status", "unknown")).upper()
    pacing_events = int(pacing.get("backoff_events", 0) or 0)
    pacing_backoff = pacing_events > 0 or bool(pacing.get("backoff"))
    overall = "OK"
    if health_status not in {"OK", "HEALTHY"} or pacing_backoff:
        overall = "DEGRADED"

    cols = st.columns(4)
    cols[0].metric("Status", overall)
    cols[1].metric("Health", health_status)
    cols[2].metric("RPM", pacing.get("rpm", 0.0))
    cols[3].metric("Backoffs", pacing_events)


def _render_telemetry_panel(state: Dict[str, Any]) -> None:
    telemetry = state.get("telemetry") or {}
    telemetry_error = state.get("telemetry_error")
    trades_error = state.get("telemetry_trades_error")
    trades = state.get("telemetry_trades") or []

    if telemetry:
        st.subheader("Telemetry Snapshot")
        metrics_cols = st.columns(3)
        metrics_cols[0].metric("Equity", _fmt_money(telemetry.get("equity")))
        metrics_cols[1].metric(
            "Buying Power", _fmt_money(telemetry.get("buying_power"))
        )
        metrics_cols[2].metric("Day PnL", _fmt_signed(telemetry.get("day_pl")))

        risk = telemetry.get("risk") or {}
        risk_cols = st.columns(4)
        kill_label = "Engaged" if risk.get("kill_switch_engaged") else "Standby"
        risk_cols[0].metric("Kill Switch", kill_label)
        risk_cols[1].metric(
            "Daily Loss Limit", _fmt_money(risk.get("daily_loss_limit"))
        )
        risk_cols[2].metric(
            "Max Portfolio", _fmt_money(risk.get("max_portfolio_notional"))
        )
        risk_cols[3].metric(
            "Max Positions", str(risk.get("max_positions") or 0)
        )
        cooldown = "Active" if risk.get("cooldown_active") else "Idle"
        st.caption(f"Cooldown: {cooldown}")
        if risk.get("kill_switch_reason"):
            st.caption(f"Kill switch reason: {risk['kill_switch_reason']}")

        orchestrator = telemetry.get("orchestrator") or {}
        orch_state = str(orchestrator.get("state") or "stopped").title()
        st.caption(
            "Orchestrator state: "
            f"{orch_state} · Can trade: {'Yes' if orchestrator.get('can_trade') else 'No'}"
        )
        if orchestrator.get("last_heartbeat"):
            st.caption(f"Last heartbeat: {orchestrator['last_heartbeat']}")
        if orchestrator.get("trade_guard_reason"):
            st.caption(f"Trade guard: {orchestrator['trade_guard_reason']}")
        if orchestrator.get("last_error"):
            st.caption(f"Last error: {orchestrator['last_error']}")
    elif telemetry_error:
        st.info("Telemetry temporarily unavailable.")

    if trades:
        st.subheader("Recent Telemetry Trades")
        trades_df = pd.DataFrame(trades)
        st.dataframe(trades_df, use_container_width=True)
    elif trades_error:
        st.info(f"Telemetry trades unavailable: {trades_error}")
    elif telemetry:
        st.caption("No recent telemetry trades available.")


def _run_full_diagnostics(client: ApiClient, state: Dict[str, Any], limit: int) -> None:
    if not state.get("backend_up"):
        return
    _fetch_health(client, state)
    _fetch_pacing(client, state)
    _fetch_telemetry(client, state)
    _fetch_logs(client, state, limit)
    _fetch_execution_tail(client, state, limit)
    state["last_diagnostics_at"] = _format_timestamp(datetime.now(timezone.utc))


def _fetch_health(client: ApiClient, state: Dict[str, Any]) -> None:
    try:
        state["health"] = client.health() or {}
        state["health_error"] = None
    except Exception as exc:  # noqa: BLE001
        state["health"] = {}
        state["health_error"] = {"path": "/health", "error": str(exc)}


def _fetch_pacing(client: ApiClient, state: Dict[str, Any]) -> None:
    try:
        payload = client.pacing()
        state["pacing"] = payload if isinstance(payload, dict) else {"raw": payload}
        state["pacing_error"] = None
    except Exception as exc:  # noqa: BLE001
        state["pacing"] = {}
        state["pacing_error"] = {"path": "/pacing", "error": str(exc)}


def _fetch_telemetry(client: ApiClient, state: Dict[str, Any]) -> None:
    if not state.get("backend_up"):
        state["telemetry"] = {}
        state["telemetry_error"] = None
        state["telemetry_trades"] = []
        state["telemetry_trades_error"] = None
        return

    try:
        payload = client.telemetry_metrics()
    except Exception as exc:  # noqa: BLE001
        state["telemetry"] = {}
        state["telemetry_error"] = str(exc)
    else:
        state["telemetry"] = payload if isinstance(payload, dict) else {}
        state["telemetry_error"] = None

    try:
        trades_payload = client.telemetry_trades()
    except Exception as exc:  # noqa: BLE001
        state["telemetry_trades"] = []
        state["telemetry_trades_error"] = str(exc)
    else:
        if isinstance(trades_payload, list):
            state["telemetry_trades"] = trades_payload
        else:
            state["telemetry_trades"] = []
        state["telemetry_trades_error"] = None


def _fetch_logs(client: ApiClient, state: Dict[str, Any], limit: int) -> None:
    if not state.get("backend_up"):
        state["log_entries"] = []
        state["logs_error"] = None
        state["last_logs_at"] = _format_timestamp(datetime.now(timezone.utc))
        return
    try:
        payload = client.logs_recent(limit=limit)
        entries = _normalize_logs(payload)
        state["log_entries"] = entries
        state["logs_error"] = None
    except Exception as exc:  # noqa: BLE001
        state["log_entries"] = []
        state["logs_error"] = {"path": "/logs/recent", "error": str(exc)}
    finally:
        state["last_logs_at"] = _format_timestamp(datetime.now(timezone.utc))


def _fetch_execution_tail(client: ApiClient, state: Dict[str, Any], limit: int) -> None:
    if not state.get("backend_up"):
        state["execution_tail"] = {"lines": []}
        state["execution_error"] = None
        return
    try:
        payload = client.execution_tail(limit=limit)
        state["execution_tail"] = payload if isinstance(payload, dict) else {"lines": []}
        state["execution_error"] = None
    except Exception as exc:  # noqa: BLE001
        state["execution_tail"] = {"lines": []}
        state["execution_error"] = {"path": "/debug/execution_tail", "error": str(exc)}


def _normalize_logs(payload: Any) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for raw in _iter_log_entries(payload):
        if isinstance(raw, dict):
            row = {
                "time": _extract_time(raw),
                "level": str(raw.get("level") or raw.get("lvl") or raw.get("severity") or ""),
                "worker": str(
                    raw.get("worker")
                    or raw.get("name")
                    or raw.get("logger")
                    or raw.get("process")
                    or ""
                ),
                "msg": _extract_message(raw),
            }
            entries.append({"text": _format_log_line(raw), "row": row})
        else:
            text = str(raw)
            entries.append({"text": text, "row": None})
    return entries


def _iter_log_entries(payload: Any) -> Iterable[Any]:
    if isinstance(payload, dict):
        for key in ("lines", "entries", "events", "data", "logs"):
            value = payload.get(key)
            if isinstance(value, list):
                for item in value:
                    yield item
        if any(k in payload for k in ("msg", "message", "level", "time", "timestamp")):
            yield payload
        return
    if isinstance(payload, (list, tuple)):
        for item in payload:
            yield item
        return
    if isinstance(payload, str):
        for line in payload.splitlines():
            yield line
        return
    yield payload


def _format_log_line(payload: Dict[str, Any]) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False)
    except Exception:  # noqa: BLE001 - best effort
        return str(payload)


def _extract_time(payload: Dict[str, Any]) -> str:
    for key in ("time", "timestamp", "ts", "@timestamp"):
        value = payload.get(key)
        if value:
            return str(value)
    summary = payload.get("summary")
    if isinstance(summary, dict) and summary.get("timestamp"):
        return str(summary.get("timestamp"))
    return ""


def _extract_message(payload: Dict[str, Any]) -> str:
    for key in ("msg", "message", "event", "text"):
        value = payload.get(key)
        if value:
            return str(value)
    summary = payload.get("summary")
    if isinstance(summary, dict) and summary.get("message"):
        return str(summary.get("message"))
    return _format_log_line(payload)


def _apply_filter(entries: List[Dict[str, Any]], needle: str) -> List[Dict[str, Any]]:
    if not needle:
        return entries
    target = needle.lower()
    filtered: List[Dict[str, Any]] = []
    for entry in entries:
        haystack = entry["text"].lower()
        row = entry.get("row") or {}
        haystack += " " + " ".join(str(v).lower() for v in row.values())
        if target in haystack:
            filtered.append(entry)
    return filtered


def _format_timestamp(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def _export_filename() -> str:
    now = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    return f"gigatrader-logs-{now}.txt"


if __name__ == "__main__":  # pragma: no cover - manual execution helper
    render()
