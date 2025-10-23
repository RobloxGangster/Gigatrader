from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable
import zipfile

import streamlit as st


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


def render():
    # Heading text must match E2E expectations exactly:
    st.header("Diagnostics / Logs")
    st.caption("System diagnostics and log export utilities.")

    if st.button("Create Repro Bundle", type="primary"):
        bundle = _create_repro_bundle()
        if bundle is not None:
            st.success(f"Repro bundle created: {bundle}")
        else:
            st.warning("Unable to create repro bundle.")

if __name__ == "__main__":
    render()
