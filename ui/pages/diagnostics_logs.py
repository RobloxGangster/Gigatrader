from __future__ import annotations

from typing import Any, Dict

import os
from datetime import datetime
from pathlib import Path
import zipfile

import streamlit as st

from ui.lib.api_client import ApiClient
from ui.lib.page_guard import require_backend

_MESSAGE_KEY = "diagnostics_logs_status"
_REFRESH_TOGGLE = "_refresh_logs_toggle"

_BUNDLE_CANDIDATES = (
    Path("config.yaml"),
    Path("config.example.yaml"),
    Path("RISK_PRESETS.md"),
    Path("logs"),
    Path("fixtures"),
    Path("ui/fixtures"),
)


def _iter_bundle_sources() -> list[Path]:
    found: list[Path] = []
    for candidate in _BUNDLE_CANDIDATES:
        path = candidate
        if path.exists():
            found.append(path)
    return found


def _archive_path(zf: zipfile.ZipFile, source: Path, *, root: Path) -> None:
    if source.is_file():
        arcname = source.relative_to(root) if source.is_relative_to(root) else source.name
        zf.write(source, arcname=str(arcname))
        return
    for child in source.rglob("*"):
        if child.is_file():
            if child.is_relative_to(root):
                arc = child.relative_to(root)
            else:
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
            _archive_path(zf, source.resolve(), root=root)
    return bundle_path
def render(*_: Any) -> None:
    st.header("Diagnostics / Logs")

    api = ApiClient()
    if not require_backend(api):
        return

    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        if st.button("Run Diagnostics", use_container_width=True):
            try:
                resp = api.diagnostics_run()
                message = str(resp.get("message") or "Diagnostics complete")
                st.session_state[_MESSAGE_KEY] = {"ok": True, "message": message}
            except Exception as exc:  # noqa: BLE001 - surface to UI
                st.session_state[_MESSAGE_KEY] = {
                    "ok": False,
                    "message": f"Diagnostics failed: {exc}",
                }
            st.rerun()
    with col2:
        if st.button("Refresh Logs", use_container_width=True):
            st.session_state[_REFRESH_TOGGLE] = not st.session_state.get(_REFRESH_TOGGLE, False)
            st.rerun()

    with col3:
        try:
            raw = api._request("GET", "/logs/download")
            if isinstance(raw, bytes):
                payload = raw
            elif isinstance(raw, str):
                payload = raw.encode("utf-8")
            else:
                payload = bytes(raw)
            st.download_button(
                "Export log file",
                data=payload,
                file_name="app.log",
                mime="text/plain",
                use_container_width=True,
            )
        except Exception as exc:  # noqa: BLE001 - surface to UI
            st.warning(f"Export unavailable: {exc}")
        if st.button("Create Repro Bundle", use_container_width=True):
            try:
                bundle_path = _create_repro_bundle()
                st.success(f"Created bundle: {bundle_path}")
            except Exception as exc:  # noqa: BLE001 - surface to UI
                st.error(f"Failed to create bundle: {exc}")

    status = st.session_state.get(_MESSAGE_KEY)
    if isinstance(status, dict) and status.get("message"):
        if status.get("ok"):
            st.success(status["message"])
        else:
            st.error(status["message"])

    st.caption("Recent application log tail")
    try:
        data = api.recent_logs(limit=500)
        lines = data.get("lines", []) if isinstance(data, dict) else []
        if lines:
            st.code("\n".join(str(line) for line in lines))
        else:
            st.info("No log lines available yet.")
    except Exception as exc:  # noqa: BLE001 - show warning to user
        st.warning(f"Unable to fetch logs: {exc}")
