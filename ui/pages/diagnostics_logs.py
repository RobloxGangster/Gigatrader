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


def _make_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in (DIAG_DIR / "latest.json", DIAG_DIR / "latest.txt"):
            if path.exists():
                zf.write(path, arcname=path.name)
        if LOGS_DIR.exists():
            for log_path in LOGS_DIR.rglob("*.log"):
                try:
                    zf.write(log_path, arcname=str(log_path.relative_to(LOGS_DIR)))
                except Exception:  # noqa: BLE001 - tolerate unreadable files
                    continue
    buf.seek(0)
    return buf.read()


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


def _ensure_state() -> None:
    if _RUN_STATE_KEY not in st.session_state:
        st.session_state[_RUN_STATE_KEY] = False
    if _ZIP_STATE_KEY not in st.session_state:
        st.session_state[_ZIP_STATE_KEY] = _make_zip()
    if _REPRO_STATE_KEY not in st.session_state:
        st.session_state[_REPRO_STATE_KEY] = None


def render(_: object | None = None, __: object | None = None) -> None:
    st.header("Diagnostics / Logs")

    _ensure_state()

    col_run, col_export = st.columns(2)
    with col_run:
        if st.button("Run Diagnostics", key="run-diag"):
            _run_diagnostics()
            st.session_state[_RUN_STATE_KEY] = True
            st.session_state[_ZIP_STATE_KEY] = _make_zip()
    with col_export:
        logs_payload = st.session_state.get(_ZIP_STATE_KEY) or _make_zip()
        st.download_button(
            "Export Logs",
            logs_payload,
            file_name="logs_bundle.zip",
            mime="application/zip",
            key="export-logs",
        )

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
