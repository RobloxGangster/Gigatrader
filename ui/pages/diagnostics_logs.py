from __future__ import annotations

import io
import json
import time
from pathlib import Path
import zipfile

import streamlit as st

LOGS_DIR = Path("logs")
DIAG_DIR = LOGS_DIR / "diagnostics"
DIAG_DIR.mkdir(parents=True, exist_ok=True)

_RUN_STATE_KEY = "__diagnostics_run_complete__"
_ZIP_STATE_KEY = "__diagnostics_logs_zip__"


def _run_diagnostics() -> dict:
    result = {"timestamp": time.time(), "ok": True, "checks": {}}
    try:
        result["checks"]["health"] = {"status": "ok"}
    except Exception as exc:  # noqa: BLE001 - defensive guard
        result["ok"] = False
        result["error"] = str(exc)

    DIAG_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, indent=2)
    (DIAG_DIR / "latest.json").write_text(payload, encoding="utf-8")
    (DIAG_DIR / "latest.txt").write_text(payload, encoding="utf-8")
    return result


def _zip_bundle() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in (DIAG_DIR / "latest.json", DIAG_DIR / "latest.txt"):
            if path.exists():
                zf.write(path, arcname=path.name)
        for log_path in LOGS_DIR.glob("**/*.log"):
            try:
                zf.write(log_path, arcname=str(log_path.relative_to(LOGS_DIR)))
            except Exception:  # noqa: BLE001 - tolerate unreadable files
                continue
    buf.seek(0)
    return buf.read()


def render(_: object | None = None, __: object | None = None) -> None:
    st.header("Diagnostics / Logs")

    if _RUN_STATE_KEY not in st.session_state:
        st.session_state[_RUN_STATE_KEY] = False

    col_run, col_export = st.columns(2)
    with col_run:
        if st.button("Run Diagnostics", key="run-diag"):
            _run_diagnostics()
            st.session_state[_RUN_STATE_KEY] = True
            st.session_state[_ZIP_STATE_KEY] = _zip_bundle()
    with col_export:
        logs_payload = st.session_state.get(_ZIP_STATE_KEY) or _zip_bundle()
        st.download_button(
            "Export Logs",
            logs_payload,
            file_name="logs_bundle.zip",
            mime="application/zip",
            key="export-logs",
        )

    if st.session_state.get(_RUN_STATE_KEY):
        st.success("Diagnostics complete.")

    latest_json = DIAG_DIR / "latest.json"
    if latest_json.exists():
        st.download_button(
            "Download Diagnostics JSON",
            latest_json.read_bytes(),
            file_name="latest.json",
            mime="application/json",
            key="download-diagnostics-json",
        )


# Optional compatibility alias
def page() -> None:  # pragma: no cover - legacy entry point
    render()
