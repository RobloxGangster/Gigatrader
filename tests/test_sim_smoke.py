"""Smoke tests for the offline simulation runner."""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys


def test_sim_produces_artifact(tmp_path, monkeypatch) -> None:
    repo = pathlib.Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["SIM_SYMBOLS"] = "AAPL"
    env["SIM_BARS_PATH"] = str(repo / "data" / "sim" / "bars_1m.csv")
    env["SIM_SENTI_PATH"] = str(repo / "data" / "sim" / "sentiment.ndjson")
    env["SIM_MAX_ROWS"] = "50"
    env["SIM_FAULTS"] = "none"
    subprocess.run(
        [sys.executable, "-m", "services.sim.run"],
        cwd=str(repo),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert (repo / "artifacts" / "sim_result.jsonl").exists()
