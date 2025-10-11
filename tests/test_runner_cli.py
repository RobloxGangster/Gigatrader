"""CLI readiness checks for the Phase 7 runner."""

from __future__ import annotations

import os
import subprocess
import sys


def _run_check(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "cli.main", "check"],
        env=env,
        capture_output=True,
        text=True,
    )


def test_cli_check_ready() -> None:
    base_env = dict(os.environ)
    base_env.pop("ALPACA_API_KEY_ID", None)
    base_env.pop("ALPACA_API_SECRET_KEY", None)
    base_env.pop("ALPACA_API_KEY", None)
    base_env.pop("ALPACA_API_SECRET", None)

    missing = _run_check(base_env)
    assert missing.returncode != 0
    assert "NOT READY" in missing.stdout

    ready_env = dict(base_env)
    ready_env["ALPACA_API_KEY_ID"] = "key"
    ready_env["ALPACA_API_SECRET_KEY"] = "secret"

    ready = _run_check(ready_env)
    assert ready.returncode == 0
    assert "READY" in ready.stdout
