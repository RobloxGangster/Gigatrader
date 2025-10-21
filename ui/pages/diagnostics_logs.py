from __future__ import annotations

import os
import zipfile
from datetime import datetime
from pathlib import Path

import streamlit as st

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


def _resolve_api(api_client: ApiClient | None = None) -> ApiClient:
    return api_client or ApiClient()


def render(*_: object, api_client: ApiClient | None = None) -> None:
    render_page(api_client)


def render_page(api_client: ApiClient | None = None) -> None:
    st.title("Diagnostics / Logs")

    api = _resolve_api(api_client)
    st.caption(f"Resolved API: {api.base()}")
    backend_ok = require_backend(api)

    col1, col2 = st.columns([1, 1])
    with col1:
        limit = st.number_input("Lines", min_value=50, max_value=5000, value=200, step=50)
    with col2:
        st.write("")

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
            st.rerun()
    with controls[2]:
        if st.button("Create Repro Bundle", use_container_width=True):
            try:
                bundle_path = _create_repro_bundle()
            except Exception as exc:  # noqa: BLE001 - surface failure
                st.error(f"Failed to create bundle: {exc}")
            else:
                st.success(f"Created bundle: {bundle_path}")

    download_placeholder = st.empty()

    if backend_ok:
        try:
            data = api.get_json("/logs/recent", params={"limit": int(limit)})
            lines = data.get("lines", []) if isinstance(data, dict) else []
            st.code("\n".join(lines) or "(no logs yet)", language="text")
            if st.button("Download logs", disabled=not backend_ok):
                try:
                    response = api.request(
                        "GET",
                        "/logs/recent",
                        params={"limit": int(limit), "as_file": True},
                    )
                except Exception as exc:  # noqa: BLE001 - show error to user
                    st.error(f"Failed to download logs: {exc}")
                else:
                    download_placeholder.download_button(
                        "Save logs",
                        response.content,
                        file_name="recent.log",
                        mime="text/plain",
                    )
        except Exception as exc:  # noqa: BLE001 - surface the failure to the UI
            st.error(f"Failed to load logs: {exc}")
    else:
        st.info("Backend unavailable — log tail and downloads are disabled.")


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
