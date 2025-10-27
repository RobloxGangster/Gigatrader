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
from ui.lib.ui_compat import safe_rerun

STATE_KEY = "__diagnostics_state__"
DEFAULT_LINES = 200
REFRESH_INTERVAL_MS = 5_000


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
        },
    )


def render() -> None:
    st.header("Diagnostics / Logs")
    st.caption("Backend health, pacing, and recent logs. Export and refresh controls below.")

    client = ApiClient()
    state = _get_state()

    if st.button("Create Repro Bundle", type="primary"):
        bundle = _create_repro_bundle()
        if bundle is not None:
            st.success(f"Repro bundle created: {bundle}")
        else:
            st.warning("Unable to create repro bundle.")

    controls = st.columns([1, 1, 1, 2])
    with controls[0]:
        run_clicked = st.button(
            "Run Diagnostics",
            type="primary",
            help="Fetch /health, /pacing, and the latest log tail.",
        )
    st.session_state.setdefault("diag.autorefresh", False)
    previous_auto = bool(state.get("auto_enabled", False))
    with controls[1]:
        auto_enabled = st.toggle(
            "Auto-refresh logs",
            value=previous_auto,
            help="Refresh the log table every five seconds without resetting state.",
        )
    with controls[2]:
        limit = int(
            st.number_input(
                "Lines",
                min_value=50,
                max_value=5000,
                value=int(state.get("limit", DEFAULT_LINES)),
                step=50,
            )
        )
    with controls[3]:
        filter_text = st.text_input(
            "Filter (contains)",
            value=str(state.get("filter", "")),
            placeholder="error, worker, order id …",
        )

    state["auto_enabled"] = auto_enabled
    st.session_state["diag.autorefresh"] = auto_enabled
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

    interval_sec = REFRESH_INTERVAL_MS / 1000.0
    now = time.time()
    if run_clicked and backend_up:
        _run_full_diagnostics(client, state, limit)
    elif auto_enabled and backend_up:
        last_auto = float(state.get("last_auto_refresh", 0.0) or 0.0)
        if not previous_auto or now - last_auto >= interval_sec:
            state["last_auto_refresh"] = now
            _fetch_logs(client, state, limit)
            _fetch_execution_tail(client, state, limit)
    elif previous_auto and not auto_enabled:
        state["last_auto_refresh"] = 0.0

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
    st.subheader("Logs & Pacing")
    st.json(pacing or {"message": "No pacing telemetry"}, expanded=False)

    entries: List[Dict[str, Any]] = state.get("log_entries", [])
    filtered_entries = _apply_filter(entries, filter_text)

    log_lines = [entry["text"] for entry in filtered_entries]
    table_rows = [entry["row"] for entry in filtered_entries if entry.get("row")]

    export_text = "\n".join(log_lines)
    st.subheader("Logs")

    st.download_button(
        "Export logs",
        data=export_text.encode("utf-8"),
        file_name=_export_filename(),
        mime="text/plain",
    )

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

    if auto_enabled and "PYTEST_CURRENT_TEST" not in os.environ:
        time.sleep(interval_sec)
        safe_rerun()


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


def _run_full_diagnostics(client: ApiClient, state: Dict[str, Any], limit: int) -> None:
    if not state.get("backend_up"):
        return
    _fetch_health(client, state)
    _fetch_pacing(client, state)
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
