#!/usr/bin/env python3
from pathlib import Path
import sys, subprocess
ROOT = Path(__file__).resolve().parents[1]
FAIL = 0
def ok(m): print(f"OK  {m}")
def fail(m): 
    global FAIL; FAIL=1; print(f"FAIL {m}")

REQUIRED = [
  "services/market/loop.py",
  "services/market/indicators.py",
  "services/market/store.py",
]
miss=[p for p in REQUIRED if not (ROOT/p).exists()]
if miss: fail("missing: " + ", ".join(miss))
else: ok("phase1 files present")

sys.path.insert(0, str(ROOT))
try:
    import services.market.loop as loop
    import services.market.indicators as ind
    import services.market.store as store
    ok("imports OK")
except Exception as ex:
    fail(f"import error: {ex}")

rc = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests"], cwd=ROOT).returncode
if rc != 0: fail(f"pytest failed (exit {rc})")
print("\nSUMMARY:", "PASS ✅" if FAIL==0 else "FAIL ❌"); sys.exit(FAIL)
