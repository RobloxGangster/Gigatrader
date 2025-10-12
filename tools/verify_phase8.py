#!/usr/bin/env python3
"""Phase 8 verification script for offline simulation regression tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAIL = False


def _print_ok(message: str) -> None:
    print(f"OK {message}")


def _print_fail(message: str) -> None:
    global FAIL
    FAIL = True
    print(f"FAIL {message}")


def must_exist() -> None:
    required = [
        "services/sim/run.py",
        "services/sim/loader.py",
        "services/sim/exec_stub.py",
        "services/strategy/engine.py",
        "services/execution/engine.py",
        "services/risk/engine.py",
        "data/sim/bars_1m.csv",
        "golden/sim_result.jsonl",
    ]
    missing = [path for path in required if not (ROOT / path).exists()]
    if missing:
        _print_fail("missing: " + ", ".join(missing))
    else:
        _print_ok("Phase-8 files present")


def run_sim() -> None:
    env = dict(os.environ)
    env.setdefault("PYTHONPATH", str(ROOT))
    env.setdefault("SIM_SYMBOLS", "AAPL,MSFT,SPY")
    env.setdefault("SIM_BARS_PATH", "data/sim/bars_1m.csv")
    env.setdefault("SIM_SENTI_PATH", "data/sim/sentiment.ndjson")
    env.setdefault("SIM_MAX_ROWS", "500")
    env.setdefault("SIM_FAULTS", "none")
    cmd = [sys.executable, "-m", "services.sim.run"]
    result = subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "")[:400]
        _print_fail(f"sim run failed: {stderr}")
    else:
        _print_ok("sim run completed")


def _normalize_lines(path: Path) -> list[str]:
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            normalized = json.dumps(json.loads(text), sort_keys=True)
        except json.JSONDecodeError:
            normalized = text
        lines.append(normalized)
    return sorted(lines)


def compare_golden() -> None:
    artifacts_path = ROOT / "artifacts" / "sim_result.jsonl"
    golden_path = ROOT / "golden" / "sim_result.jsonl"
    if not artifacts_path.exists():
        _print_fail("sim_result.jsonl missing")
        return
    if not golden_path.exists():
        _print_fail("golden/sim_result.jsonl missing")
        return
    sim_lines = _normalize_lines(artifacts_path)
    golden_lines = _normalize_lines(golden_path)
    if sim_lines != golden_lines:
        _print_fail("golden mismatch (order-insensitive compare). Update golden if intended.")
    else:
        _print_ok("golden match")


def main() -> None:
    must_exist()
    run_sim()
    compare_golden()
    print("\nSUMMARY: " + ("PASS ✅" if not FAIL else "FAIL ❌"))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
