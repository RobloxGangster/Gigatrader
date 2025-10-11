#!/usr/bin/env python3
from __future__ import annotations
import os, re, sys, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAIL = 0
def ok(m): print(f"OK  {m}")
def fail(m):
    global FAIL; FAIL = 1; print(f"FAIL {m}")

REQUIRED = [
  "services/risk/__init__.py",
  "services/risk/presets.py",
  "services/risk/state.py",
  "services/risk/engine.py",
  "services/gateway/__init__.py",
  "services/gateway/proposals.py",
  "tests/test_risk_engine.py",
]

def must_exist():
    miss = [p for p in REQUIRED if not (ROOT/p).exists()]
    if miss: fail("missing: " + ", ".join(miss))
    else: ok("Phase-2 files present")

def grep_tokens():
    e = (ROOT/"services/risk/engine.py").read_text(errors="ignore")
    for t in ["class RiskManager","class Proposal","class Decision","def pre_trade_check","_risk_budget_dollars"]:
        if t not in e: fail(f"engine.py missing: {t}")
    s = (ROOT/"services/risk/state.py").read_text(errors="ignore")
    for t in ["class StateProvider","get_account_equity","class InMemoryState"]:
        if t not in s: fail(f"state.py missing: {t}")
    p = (ROOT/"services/risk/presets.py").read_text(errors="ignore")
    for t in ["PRESETS","RiskPreset"]:
        if t not in p: fail(f"presets.py missing: {t}")
    g = (ROOT/"services/gateway/proposals.py").read_text(errors="ignore")
    for t in ["class Gateway","propose_order","RiskManager","Proposal","Decision"]:
        if t not in g: fail(f"gateway/proposals.py missing: {t}")
    if FAIL == 0: ok("Symbols present in Phase-2 modules")

def import_sanity():
    sys.path.insert(0, str(ROOT))
    try:
        import services.risk.engine as eng
        import services.risk.state as st
    except Exception as ex:
        fail(f"import error: {ex}")
        return
    for cls in ["RiskManager","Proposal","Decision"]:
        if not hasattr(eng, cls): fail(f"engine missing {cls}")
    if not hasattr(st, "StateProvider") or not hasattr(st, "InMemoryState"):
        fail("state API incomplete")
    if FAIL == 0: ok("Imports & API shape OK")

def quick_env_checks():
    os.environ["RISK_PROFILE"]="balanced"
    overrides = {
        "DAILY_LOSS_LIMIT":"1000","PER_TRADE_RISK_PCT":"0.5","MAX_POSITIONS":"5",
        "MAX_NOTIONAL":"50000","MAX_SYMBOL_NOTIONAL":"15000","COOLDOWN_SEC":"180",
        "KILL_SWITCH":"false","OPTIONS_MIN_OI":"150","OPTIONS_MIN_VOLUME":"75",
        "OPTIONS_DELTA_MIN":"0.18","OPTIONS_DELTA_MAX":"0.40",
    }
    os.environ.update(overrides)
    try:
        import services.risk.engine as eng; import services.risk.state as st
        _ = eng.RiskManager(st.InMemoryState())
        ok("Env overrides accepted by RiskManager")
    except Exception as ex:
        fail(f"RiskManager ctor failed: {ex}")

def run_pytests():
    cmd = [sys.executable, "-m", "pytest", "-q", "tests/test_risk_engine.py"]
    print("$ "+" ".join(cmd))
    res = subprocess.run(cmd, cwd=str(ROOT))
    if res.returncode != 0: fail("pytest failed")
    else: ok("pytest passed")

def main():
    must_exist()
    grep_tokens()
    import_sanity()
    quick_env_checks()
    run_pytests()
    print("\nSUMMARY: " + ("PASS ✅" if FAIL==0 else "FAIL ❌"))
    sys.exit(FAIL)

if __name__ == "__main__":
    main()
