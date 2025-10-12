#!/usr/bin/env python3
"""CI helper validating Phase 7 orchestration requirements."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAIL = False

REQUIRED = [
    "services/runtime/logging.py",
    "services/runtime/metrics.py",
    "services/runtime/runner.py",
    "cli/main.py",
    "services/strategy/engine.py",
    "services/sentiment/poller.py",
    "services/execution/engine.py",
    "services/risk/engine.py",
    "services/risk/state.py",
]


def ok(message: str) -> None:
    print(f"OK {message}")


def fail(message: str) -> None:
    global FAIL
    FAIL = True
    print(f"FAIL {message}")


def must_exist() -> None:
    missing = [path for path in REQUIRED if not (ROOT / path).exists()]
    if missing:
        fail("missing: " + ", ".join(missing))
    else:
        ok("Phase-7 files present")


def import_sanity() -> None:
    sys.path.insert(0, str(ROOT))
    try:
        import services.runtime.runner as runner  # noqa: F401
        import services.runtime.logging as logging_mod  # noqa: F401
        import services.runtime.metrics as metrics_mod  # noqa: F401
        import cli.main as cli_main  # noqa: F401
    except Exception as exc:  # pragma: no cover - executed in subprocess
        fail(f"import error: {exc}")
        return
    for module, attr in [
        (runner, "Runner"),
        (logging_mod, "setup_logging"),
        (metrics_mod, "Metrics"),
    ]:
        if not hasattr(module, attr):
            fail(f"{module.__name__} missing {attr}")
    ok("Imports & API shape OK")


def run_unit_subset() -> None:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "tests/test_strategy_engine.py",
        "tests/test_options_select.py",
        "tests/test_execution_engine.py",
        "tests/test_risk_engine.py",
        "tests/test_sentiment_pipeline.py",
    ]
    print("$ " + " ".join(cmd))
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(ROOT))
    result = subprocess.run(cmd, cwd=str(ROOT), env=env)
    if result.returncode != 0:
        fail("pytest failed")
    else:
        ok("pytest subset passed")


def main() -> None:
    must_exist()
    import_sanity()
    run_unit_subset()
    print("\nSUMMARY: " + ("PASS ✅" if not FAIL else "FAIL ❌"))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":  # pragma: no cover - script entry point
    main()
