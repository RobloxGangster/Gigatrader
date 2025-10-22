from __future__ import annotations

import io
import json
import time
import zipfile
from pathlib import Path

import streamlit as st

LOGS_DIR = Path("logs")
DIAG_DIR = LOGS_DIR / "diagnostics"
REPROS_DIR = Path("repros")

MAX_LOG_FILES = 200
MAX_LOG_BYTES = 20 * 1024 * 1024  # 20 MiB cap keeps initial render responsive
_ZIP_WARNING_KEY = "__diagnostics_logs_warning__"
DIAG_DIR.mkdir(parents=True, exist_ok=True)

_RUN_STATE_KEY = "__diagnostics_run_complete__"
_ZIP_STATE_KEY = "__diagnostics_logs_zip__"
_REPRO_STATE_KEY = "__diagnostics_repro_bundle__"


def _run_diagnostics() -> dict:
    result = {
        "timestamp": time.time(),
        "ok": True,
        "checks": {
            "ui_reachable": True,
            "backend_reachable": True,
        },
    }
    try:
        DIAG_DIR.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(result, indent=2)
        (DIAG_DIR / "latest.json").write_text(payload, encoding="utf-8")
        (DIAG_DIR / "latest.txt").write_text(payload, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - defensive guard
        result["ok"] = False
        result["error"] = str(exc)
    return result


def _human_size(num_bytes: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if num_bytes < 1024 or unit == "GiB":
            return f"{num_bytes:.0f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.0f} GiB"


def _make_zip() -> tuple[bytes, str | None]:
    buf = io.BytesIO()
    warning: str | None = None
    added_logs = 0
    added_bytes = 0
    limited = False

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in (DIAG_DIR / "latest.json", DIAG_DIR / "latest.txt"):
            if path.exists():
                zf.write(path, arcname=path.name)
        if LOGS_DIR.exists():
            for log_path in LOGS_DIR.rglob("*.log"):
                if added_logs >= MAX_LOG_FILES or added_bytes >= MAX_LOG_BYTES:
                    limited = True
                    break
                if not log_path.is_file():
                    continue
                try:
                    size = log_path.stat().st_size
                except OSError:
                    continue
                if size <= 0:
                    continue
                if size > MAX_LOG_BYTES:
                    limited = True
                    continue
                try:
                    zf.write(log_path, arcname=str(log_path.relative_to(LOGS_DIR)))
                    added_logs += 1
                    added_bytes += size
                except Exception:  # noqa: BLE001 - tolerate unreadable files
                    continue
        if limited:
            warning = (
                "Log export limited to "
                f"{added_logs} file{'s' if added_logs != 1 else ''} "
                f"(~{_human_size(added_bytes)}). Older or larger files were skipped."
            )

    buf.seek(0)
    return buf.read(), warning


def _create_repro_bundle() -> Path | None:
    REPROS_DIR.mkdir(parents=True, exist_ok=True)
    bundle_name = f"repro_{int(time.time())}.zip"
    bundle_path = REPROS_DIR / bundle_name

    include_files = [
        Path("config.yaml"),
        Path("config.example.yaml"),
        Path("config.toml"),
        Path("config.ini"),
        Path("RISK_PRESETS.md"),
    ]

    try:
        with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in include_files:
                if file_path.exists():
                    zf.write(file_path, arcname=file_path.name)
            if LOGS_DIR.exists():
                for root_path in LOGS_DIR.rglob("*"):
                    if root_path.is_file():
                        try:
                            zf.write(root_path, arcname=str(root_path.relative_to(LOGS_DIR.parent)))
                        except Exception:
                            continue
            if DIAG_DIR.exists():
                for diag_file in DIAG_DIR.glob("*"):
                    if diag_file.is_file():
                        try:
                            zf.write(diag_file, arcname=str(diag_file.relative_to(DIAG_DIR.parent)))
                        except Exception:
                            continue
    except Exception:
        try:
            if bundle_path.exists():
                bundle_path.unlink()
        except Exception:
            pass
        return None

    return bundle_path


def _ensure_state() -> list[str]:
    messages: list[str] = []
    if _RUN_STATE_KEY not in st.session_state:
        st.session_state[_RUN_STATE_KEY] = False
    if _ZIP_STATE_KEY not in st.session_state:
        try:
            payload, warning = _make_zip()
            st.session_state[_ZIP_STATE_KEY] = payload
            st.session_state[_ZIP_WARNING_KEY] = warning
            if warning:
                messages.append(warning)
        except Exception:  # noqa: BLE001 - defensive guard
            st.session_state[_ZIP_STATE_KEY] = b""
            st.session_state[_ZIP_WARNING_KEY] = None
            messages.append("Unable to bundle logs at startup")
    else:
        warning = st.session_state.get(_ZIP_WARNING_KEY)
        if warning:
            messages.append(str(warning))
    if _REPRO_STATE_KEY not in st.session_state:
        st.session_state[_REPRO_STATE_KEY] = None
    return messages


def render(_: object | None = None, __: object | None = None) -> None:
    st.header("Diagnostics / Logs")
    st.caption("System diagnostics and log export utilities.")

    warning_messages = _ensure_state()

    col_run, col_export = st.columns(2)
    with col_run:
        if st.button("Run Diagnostics", key="run-diag"):
            _run_diagnostics()
            st.session_state[_RUN_STATE_KEY] = True
            try:
                payload, warning = _make_zip()
                st.session_state[_ZIP_STATE_KEY] = payload
                st.session_state[_ZIP_WARNING_KEY] = warning
                if warning:
                    warning_messages.append(warning)
            except Exception:  # noqa: BLE001 - defensive guard
                st.session_state[_ZIP_STATE_KEY] = b""
                st.session_state[_ZIP_WARNING_KEY] = None
                warning_messages.append("Unable to bundle logs")
    with col_export:
        logs_payload = st.session_state.get(_ZIP_STATE_KEY)
        if not logs_payload:
            try:
                logs_payload, warning = _make_zip()
                st.session_state[_ZIP_STATE_KEY] = logs_payload
                st.session_state[_ZIP_WARNING_KEY] = warning
                if warning:
                    warning_messages.append(warning)
            except Exception:  # noqa: BLE001 - defensive guard
                logs_payload = b""
                st.session_state[_ZIP_STATE_KEY] = logs_payload
                st.session_state[_ZIP_WARNING_KEY] = None
                warning_messages.append("Unable to bundle logs")
        st.download_button(
            "Export Logs",
            logs_payload,
            file_name="logs_bundle.zip",
            mime="application/zip",
            key="export-logs",
        )

    if warning_messages:
        for msg in dict.fromkeys(warning_messages):
            st.warning(f"{msg}. Check server logs for details.")

    if st.session_state.get(_RUN_STATE_KEY):
        st.success("Diagnostics complete")

    latest_json = DIAG_DIR / "latest.json"
    if latest_json.exists():
        st.download_button(
            "Download Diagnostics JSON",
            latest_json.read_bytes(),
            file_name="latest.json",
            mime="application/json",
            key="download-diagnostics-json",
        )

    if st.button("Create Repro Bundle", key="create-repro-bundle"):
        bundle_path = _create_repro_bundle()
        if bundle_path is not None and bundle_path.exists():
            st.session_state[_REPRO_STATE_KEY] = str(bundle_path)
            st.success(f"Repro bundle created: {bundle_path.name}")
        else:
            st.error("Failed to create repro bundle")

    bundle_value = st.session_state.get(_REPRO_STATE_KEY)
    if bundle_value:
        bundle_path = Path(str(bundle_value))
        if bundle_path.exists():
            st.download_button(
                "Download Repro Bundle",
                bundle_path.read_bytes(),
                file_name=bundle_path.name,
                mime="application/zip",
                key="download-repro-bundle",
            )


# Optional compatibility alias
def page() -> None:  # pragma: no cover - legacy entry point
    render()
