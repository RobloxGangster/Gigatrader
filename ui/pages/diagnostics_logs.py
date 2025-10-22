from __future__ import annotations

from datetime import datetime
from pathlib import Path
import zipfile
from typing import Iterable

import streamlit as st


def render() -> None:
    st.header("Diagnostics / Logs")
    st.caption("Quick view of backend health, pacing and recent logs.")

    cols = st.columns([1, 1, 1])
    with cols[0]:
        if st.button("Ping /health", type="primary"):
            st.session_state["diag.last_action"] = (
                f"Pinged health @ {datetime.utcnow().isoformat()}Z"
            )
    with cols[1]:
        st.download_button(
            "Export latest log",
            data=_fake_log(),
            file_name="gigatrader-latest.log",
        )
    with cols[2]:
        st.toggle("Auto-refresh", key="diag.autorefresh")

    if st.button("Create Repro Bundle", type="primary"):
        bundle_path = _create_repro_bundle()
        st.session_state["diag.last_action"] = f"Created {bundle_path.name}"
        st.success(f"Repro bundle created: {bundle_path.name}")

    st.write(st.session_state.get("diag.last_action", "—"))


def _fake_log() -> str:
    # keep a stub; real impl can call backend /logs
    return "[info] diagnostics stub\n"


def _create_repro_bundle() -> Path:
    root = Path.cwd()
    output_dir = root / "repros"
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    bundle_path = output_dir / f"repro_{timestamp}.zip"
    sources = list(_bundle_sources(root))

    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for source in sources:
            arcname = source.relative_to(root)
            zf.write(source, arcname)

    st.session_state["diag.last_bundle"] = str(bundle_path)
    return bundle_path


def _bundle_sources(root: Path) -> Iterable[Path]:
    config_candidates = [
        root / "config.yaml",
        root / "config.example.yaml",
        root / "RISK_PRESETS.md",
    ]
    for candidate in config_candidates:
        if candidate.exists():
            yield candidate

    fixtures_dir = root / "fixtures"
    if fixtures_dir.exists():
        for path in fixtures_dir.rglob("*"):
            if path.is_file():
                yield path
