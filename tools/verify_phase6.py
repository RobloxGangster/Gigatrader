#!/usr/bin/env python3
from pathlib import Path
import sys, subprocess
ROOT = Path(__file__).resolve().parents[1]
FAIL = 0
def ok(m): print(f"OK  {m}")
def fail(m): 
    global FAIL; FAIL=1; print(f"FAIL {m}")

REQUIRED = [
  "services/strategy/engine.py",
  "services/strategy/equities.py",
  "services/strategy/options_strat.py",
  "services/execution/engine.py",
  "services/gateway/options.py",
  "services/risk/engine.py",
  "services/risk/state.py",
]
miss=[p for p in REQUIRED if not (ROOT/p).exists()]
if miss: fail("missing: " + ", ".join(miss))
else: ok("phase6 files present")

sys.path.insert(0, str(ROOT))
try:
    import services.strategy.engine as SENG
    import services.strategy.equities as SEQ
    import services.strategy.options_strat as SOP
    import services.execution.engine as XENG
    import services.gateway.options as OPTGW
    import services.risk.engine as RISK
    import services.risk.state as RSTATE
    ok("imports OK")
except Exception as ex:
    fail(f"import error: {ex}")

rc = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests"], cwd=ROOT).returncode
if rc != 0: fail(f"pytest failed (exit {rc})")
print("\nSUMMARY:", "PASS ✅" if FAIL==0 else "FAIL ❌"); sys.exit(FAIL)
