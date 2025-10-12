#!/usr/bin/env python3
"""Phase 2 verification script for risk management deliverables."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
FAIL = False


def ok(message: str) -> None:
    print(f"OK {message}")


def fail(message: str) -> None:
    global FAIL
    FAIL = True
    print(f"FAIL {message}")


def must_exist(paths: Iterable[str]) -> None:
    missing = [path for path in paths if not (ROOT / path).exists()]
    if missing:
        fail("missing: " + ", ".join(missing))
    else:
        ok("Required files present")


def grep_tokens() -> None:
    engine_text = (ROOT / "services/risk/engine.py").read_text(encoding="utf-8", errors="ignore")
    for token in ["class RiskManager", "class Proposal", "class Decision", "def pre_trade_check"]:
        if token not in engine_text:
            fail(f"services/risk/engine.py missing: {token}")

    state_text = (ROOT / "services/risk/state.py").read_text(encoding="utf-8", errors="ignore")
    for token in ["class StateProvider", "class InMemoryState", "get_account_equity"]:
        if token not in state_text:
            fail(f"services/risk/state.py missing: {token}")

    presets_text = (ROOT / "services/risk/presets.py").read_text(encoding="utf-8", errors="ignore")
    for token in ["PRESETS", "RiskPreset"]:
        if token not in presets_text:
            fail(f"services/risk/presets.py missing: {token}")

    gateway_text = (ROOT / "services/gateway/proposals.py").read_text(encoding="utf-8", errors="ignore")
    for token in ["class Gateway", "RiskManager", "Proposal", "Decision"]:
        if token not in gateway_text:
            fail(f"services/gateway/proposals.py missing: {token}")

    if not FAIL:
        ok("Symbols present in risk modules")


def import_sanity() -> None:
    sys.path.insert(0, str(ROOT))
    try:
        import services.risk.engine as risk_engine
        import services.risk.state as risk_state
        import services.gateway.proposals as proposals
    except Exception as exc:  # pragma: no cover - executed in CI
        fail(f"import error: {exc}")
        return

    for module, attr in [
        (risk_engine, "RiskManager"),
        (risk_engine, "Proposal"),
        (risk_engine, "Decision"),
        (risk_state, "StateProvider"),
        (risk_state, "InMemoryState"),
        (proposals, "Gateway"),
    ]:
        if not hasattr(module, attr):
            fail(f"{module.__name__} missing {attr}")

    if not FAIL:
        ok("Imports & API surface look good")


def quick_env_checks() -> None:
    os.environ.setdefault("RISK_PROFILE", "balanced")
    overrides = {
        "DAILY_LOSS_LIMIT": "1000",
        "PER_TRADE_RISK_PCT": "0.5",
        "MAX_POSITIONS": "5",
        "MAX_NOTIONAL": "50000",
        "MAX_SYMBOL_NOTIONAL": "15000",
        "COOLDOWN_SEC": "180",
        "KILL_SWITCH": "false",
        "OPTIONS_MIN_OI": "150",
        "OPTIONS_MIN_VOLUME": "75",
        "OPTIONS_DELTA_MIN": "0.18",
        "OPTIONS_DELTA_MAX": "0.40",
    }
    os.environ.update(overrides)
    try:
        import services.risk.engine as risk_engine
        import services.risk.state as risk_state

        risk_engine.RiskManager(risk_state.InMemoryState())
    except Exception as exc:  # pragma: no cover - defensive
        fail(f"RiskManager init failed: {exc}")
    else:
        ok("RiskManager accepts env overrides")


def run_pytests() -> None:
    cmd = [sys.executable, "-m", "pytest", "-q", "tests/test_risk_engine.py"]
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(ROOT))
    print("$ " + " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(ROOT), env=env, check=False)
    if result.returncode != 0:
        fail("pytest failed")
    else:
        ok("pytest passed")


def main() -> None:
    must_exist(
        [
            "services/risk/__init__.py",
            "services/risk/presets.py",
            "services/risk/state.py",
            "services/risk/engine.py",
            "services/gateway/__init__.py",
            "services/gateway/proposals.py",
            "tests/test_risk_engine.py",
        ]
    )
    grep_tokens()
    import_sanity()
    quick_env_checks()
    run_pytests()
    print("\nSUMMARY: " + ("PASS ✅" if not FAIL else "FAIL ❌"))
    sys.exit(0 if not FAIL else 1)


if __name__ == "__main__":  # pragma: no cover - script entry point
    main()
