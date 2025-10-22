from __future__ import annotations

import io
import json
import os
import zipfile
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable

import streamlit as st

from ui.lib.api_client import ApiClient
from ui.lib.page_guard import require_backend

DIAGNOSTICS_DIR = Path("logs/diagnostics")
LOG_ROOT = Path("logs")
DEFAULT_LOG_FILE = LOG_ROOT / "app.log"
_BUNDLE_CANDIDATES = (
    Path("config.yaml"),
    Path("config.example.yaml"),
    Path("RISK_PRESETS.md"),
    Path("logs"),
    Path("fixtures"),
    Path("ui/fixtures"),
)
_DIAG_STATE_KEY = "__diagnostics_bundle__"
_LOG_EXPORT_STATE_KEY = "__log_export_bundle__"


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_log_tail(path: Path, limit: int) -> list[str]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            window = deque(handle, maxlen=int(limit))
    except OSError:
        return []
    return [line.rstrip("\n") for line in window]


def _collect_backend_snapshot(api: ApiClient) -> Dict[str, Any]:
    snapshot: Dict[str, Any] = {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "backend_base": api.base(),
    }
    try:
        snapshot["health"] = api.health()
    except Exception as exc:  # noqa: BLE001
        snapshot["health_error"] = str(exc)
    try:
        snapshot["status"] = api.status()
    except Exception as exc:  # noqa: BLE001
        snapshot["status_error"] = str(exc)
    try:
        snapshot["orchestrator"] = api.orchestrator_status()
    except Exception as exc:  # noqa: BLE001
        snapshot["orchestrator_error"] = str(exc)
    try:
        snapshot["stream"] = api.stream_status()
    except Exception as exc:  # noqa: BLE001
        snapshot["stream_error"] = str(exc)
    return snapshot


def _write_diagnostics(snapshot: Dict[str, Any]) -> tuple[Path, Path, bytes]:
    diagnostics_dir = _ensure_dir(DIAGNOSTICS_DIR)
    json_payload = json.dumps(snapshot, indent=2, sort_keys=True)
    text_lines = [
        f"Diagnostics generated: {snapshot.get('generated_at', 'unknown')}",
        f"Backend base: {snapshot.get('backend_base', 'n/a')}",
    ]
    health = snapshot.get("health")
    if isinstance(health, dict):
        text_lines.append(f"Health: {json.dumps(health, sort_keys=True)}")
    elif snapshot.get("health_error"):
        text_lines.append(f"Health error: {snapshot['health_error']}")
    orchestrator = snapshot.get("orchestrator")
    if isinstance(orchestrator, dict):
        text_lines.append(
            "Orchestrator: "
            + json.dumps(
                {
                    "running": orchestrator.get("running"),
                    "kill_switch": orchestrator.get("kill_switch"),
                    "last_tick_ts": orchestrator.get("last_tick_ts"),
                },
                sort_keys=True,
            )
        )
    elif snapshot.get("orchestrator_error"):
        text_lines.append(f"Orchestrator error: {snapshot['orchestrator_error']}")
    stream = snapshot.get("stream")
    if isinstance(stream, dict):
        text_lines.append(
            "Stream: "
            + json.dumps(
                {
                    "running": stream.get("running"),
                    "source": stream.get("source"),
                    "last_heartbeat": stream.get("last_heartbeat"),
                },
                sort_keys=True,
            )
        )
    elif snapshot.get("stream_error"):
        text_lines.append(f"Stream error: {snapshot['stream_error']}")

    json_path = diagnostics_dir / "latest.json"
    text_path = diagnostics_dir / "latest.txt"
    json_path.write_text(json_payload, encoding="utf-8")
    text_blob = "\n".join(text_lines)
    text_path.write_text(text_blob, encoding="utf-8")

    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("latest.json", json_payload.encode("utf-8"))
        zf.writestr("latest.txt", text_blob.encode("utf-8"))
    bundle.seek(0)
    return json_path, text_path, bundle.read()


def _iter_log_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    files: list[Path] = []
    for child in root.rglob("*"):
        if child.is_file():
            files.append(child)
    return files


def _build_logs_export(extra_files: Iterable[Path] = ()) -> tuple[str, bytes]:
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for log_file in _iter_log_files(LOG_ROOT):
            try:
                zf.write(log_file, arcname=str(log_file.relative_to(LOG_ROOT.parent)))
            except Exception:  # noqa: BLE001
                continue
        for extra in extra_files:
            if extra.exists() and extra.is_file():
                try:
                    zf.write(extra, arcname=f"diagnostics/{extra.name}")
                except Exception:  # noqa: BLE001
                    continue
    buffer.seek(0)
    return f"logs_export_{timestamp}.zip", buffer.read()


def _iter_bundle_sources() -> list[Path]:
    found: list[Path] = []
    for candidate in _BUNDLE_CANDIDATES:
        if candidate.exists():
            found.append(candidate)
    return found


def _archive_path(zf: zipfile.ZipFile, source: Path, *, root: Path) -> None:
    if source.is_file():
        try:
            arcname = source.relative_to(root)
        except ValueError:
            arcname = source.name
        zf.write(source, arcname=str(arcname))
        return
    for child in source.rglob("*"):
        if child.is_file():
            try:
                arc = child.relative_to(root)
            except ValueError:
                arc = child.name
            zf.write(child, arcname=str(arc))


def _create_repro_bundle() -> Path:
    dest_dir = Path("repros")
    dest_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    bundle_path = dest_dir / f"repro_{timestamp}.zip"
    root = Path(os.getcwd()).resolve()
    sources = _iter_bundle_sources()

    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for source in sources:
            _archive_path(zf, source, root=root)
    return bundle_path


def render(*_: object, api_client: ApiClient | None = None) -> None:
    st.header("Diagnostics / Logs")
    st.markdown('<div data-testid="page-diagnostics"></div>', unsafe_allow_html=True)
    api = api_client or ApiClient()
    st.caption(f"Resolved API: {api.base()}")
    backend_ok = require_backend(api)

    st.divider()
    controls = st.columns([1, 1, 1])
    with controls[0]:
        if st.button("Run Diagnostics", use_container_width=True):
            with st.spinner("Collecting diagnostics..."):
                snapshot = (
                    _collect_backend_snapshot(api)
                    if backend_ok
                    else {
                        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                        "backend_base": api.base(),
                        "error": "Backend offline",
                    }
                )
                json_path, text_path, bundle = _write_diagnostics(snapshot)
                st.session_state[_DIAG_STATE_KEY] = {
                    "name": "diagnostics_latest.zip",
                    "data": bundle,
                    "json_path": str(json_path),
                    "text_path": str(text_path),
                }
            st.success("Diagnostics complete")
    with controls[1]:
        if st.button("Export Logs", use_container_width=True):
            with st.spinner("Bundling logs..."):
                diag_bundle = st.session_state.get(_DIAG_STATE_KEY)
                extras = []
                if isinstance(diag_bundle, dict):
                    for path_key in ("json_path", "text_path"):
                        path_str = diag_bundle.get(path_key)
                        if path_str:
                            extras.append(Path(path_str))
                name, payload = _build_logs_export(extras)
                st.session_state[_LOG_EXPORT_STATE_KEY] = {"name": name, "data": payload}
            st.success("Logs export ready")
    with controls[2]:
        if st.button("Create Repro Bundle", use_container_width=True):
            try:
                bundle_path = _create_repro_bundle()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Failed to create bundle: {exc}")
            else:
                st.success(f"Created bundle: {bundle_path}")

    diag_state = st.session_state.get(_DIAG_STATE_KEY)
    if isinstance(diag_state, dict) and diag_state.get("data"):
        st.download_button(
            "Download diagnostics bundle",
            diag_state["data"],
            file_name=diag_state.get("name", "diagnostics_latest.zip"),
            mime="application/zip",
            use_container_width=True,
        )

    log_state = st.session_state.get(_LOG_EXPORT_STATE_KEY)
    if isinstance(log_state, dict) and log_state.get("data"):
        st.download_button(
            "Download logs export",
            log_state["data"],
            file_name=log_state.get("name", "logs_export.zip"),
            mime="application/zip",
            use_container_width=True,
        )

    st.divider()
    st.subheader("Recent Log Tail")
    log_limit = st.slider("Lines", min_value=50, max_value=2000, value=200, step=50)
    lines = _read_log_tail(DEFAULT_LOG_FILE, log_limit)
    if lines:
        st.code("\n".join(lines[-log_limit:]), language="text")
    else:
        st.info("No log lines available.")

    if backend_ok:
        st.caption("Backend reachable — diagnostics and log exports use live data.")
    else:
        st.warning("Backend offline — diagnostics may contain cached or limited data.")
