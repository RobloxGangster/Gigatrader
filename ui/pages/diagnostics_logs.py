from __future__ import annotations

import io
import os
import time
import zipfile
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

import streamlit as st

from ui._compat import safe_rerun
from ui.lib.api_client import ApiClient
from ui.lib.page_guard import require_backend

_BUNDLE_CANDIDATES = (
    Path("config.yaml"),
    Path("config.example.yaml"),
    Path("RISK_PRESETS.md"),
    Path("logs"),
    Path("fixtures"),
    Path("ui/fixtures"),
)

_DEFAULT_LOG_PATH = Path("logs/app.log")


def _resolve_api(api_client: ApiClient | None = None) -> ApiClient:
    return api_client or ApiClient()


def _read_log_tail(path: Path, limit: int) -> list[str]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            window = deque(handle, maxlen=int(limit))
    except OSError:
        return []
    return [line.rstrip("\n") for line in window]


def _build_log_archive(lines: Sequence[str], extra_paths: Iterable[Path]) -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("recent.log", "\n".join(lines).encode("utf-8"))
        for entry in extra_paths:
            if entry.exists() and entry.is_file():
                try:
                    zf.write(entry, arcname=entry.name)
                except OSError:
                    continue
    payload.seek(0)
    return payload.read()


def render(*_: object, api_client: ApiClient | None = None) -> None:
    render_page(api_client)


def render_page(api_client: ApiClient | None = None) -> None:
    st.title("Diagnostics / Logs")
    st.caption("Inspect backend health, stream recent logs, and export diagnostics bundles.")
    api = _resolve_api(api_client)
    st.caption(f"Resolved API: {api.base()}")
    backend_ok = require_backend(api)

    col1, col2 = st.columns([1, 1])
    with col1:
        limit = int(
            st.number_input("Log lines", min_value=50, max_value=5000, value=200, step=50)
        )
    with col2:
        refresh_seconds = int(
            st.number_input("Auto refresh (s)", min_value=2, max_value=60, value=5, step=1)
        )

    auto_refresh = st.checkbox("Auto refresh", value=True, key="diagnostics_auto_refresh")

    controls = st.columns([1, 1, 1])
    with controls[0]:
        if st.button("Run Diagnostics", use_container_width=True, disabled=not backend_ok):
            try:
                result = api.diagnostics_run()
            except Exception as exc:  # noqa: BLE001 - surface failure
                st.error(f"Diagnostics failed: {exc}")
            else:
                message = (
                    result.get("message") if isinstance(result, dict) else "Diagnostics complete"
                )
                st.success(str(message))
    with controls[1]:
        if st.button("Refresh Logs", use_container_width=True):
            st.session_state["diagnostics_refresh_due"] = time.time() + refresh_seconds
            safe_rerun()
    with controls[2]:
        if st.button("Create Repro Bundle", use_container_width=True):
            try:
                bundle_path = _create_repro_bundle()
            except Exception as exc:  # noqa: BLE001 - surface failure
                st.error(f"Failed to create bundle: {exc}")
            else:
                st.success(f"Created bundle: {bundle_path}")

    lines: list[str] = []
    backend_error: str | None = None

    if backend_ok:
        try:
            data = api.get_json("/logs/recent", params={"limit": limit})
        except Exception as exc:  # noqa: BLE001 - surface the failure
            backend_error = str(exc)
            lines = _read_log_tail(_DEFAULT_LOG_PATH, limit)
        else:
            lines = data.get("lines", []) if isinstance(data, dict) else []
    else:
        lines = _read_log_tail(_DEFAULT_LOG_PATH, limit)

    if not lines:
        st.info("No log lines available yet.")
    else:
        st.code("\n".join(lines), language="text")

    if backend_error:
        st.warning(f"Backend log stream unavailable: {backend_error}")
    elif not backend_ok:
        st.error("Backend offline — displaying local log tail.")
    else:
        st.success("Backend log stream active.")

    archive_bytes: bytes | None = None
    if backend_ok:
        try:
            response = api.request(
                "GET",
                "/logs/recent",
                params={"limit": limit, "as_file": True},
            )
        except Exception:
            archive_bytes = None
        else:
            archive_bytes = response.content
    if archive_bytes is None:
        archive_bytes = _build_log_archive(lines, [_DEFAULT_LOG_PATH])

    st.download_button(
        "Download logs",
        archive_bytes,
        file_name="logs.zip",
        mime="application/zip",
        use_container_width=True,
    )

    if auto_refresh:
        now = time.time()
        refresh_due = st.session_state.get("diagnostics_refresh_due")
        if refresh_due is None:
            st.session_state["diagnostics_refresh_due"] = now + refresh_seconds
        elif now >= refresh_due:
            st.session_state["diagnostics_refresh_due"] = now + refresh_seconds
            safe_rerun()
        else:
            remaining = max(0, int(refresh_due - now))
            st.caption(f"Auto refresh in {remaining}s")
    else:
        st.session_state.pop("diagnostics_refresh_due", None)


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
