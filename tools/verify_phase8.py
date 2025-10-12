#!/usr/bin/env python3
from pathlib import Path
import sys, subprocess, json
ROOT = Path(__file__).resolve().parents[1]
FAIL = 0
def ok(m): print(f"OK  {m}")
def fail(m): 
    global FAIL; FAIL=1; print(f"FAIL {m}")

REQUIRED = [
  "services/sim/run.py",
  "services/sim/loader.py",
  "services/sim/exec_stub.py",
  "golden/sim_result.jsonl",
  "data/sim/bars_1m.csv",
]
miss=[p for p in REQUIRED if not (ROOT/p).exists()]
if miss: fail("missing: " + ", ".join(miss))
else: ok("phase8 files present")

sys.path.insert(0, str(ROOT))
try:
    import services.sim.run as SIM
    ok("imports OK")
except Exception as ex:
    fail(f"import error: {ex}")

# Run sim (should create artifacts/sim_result.jsonl) then compare to golden (order-insensitive)
cmd=[sys.executable,"-m","services.sim.run"]
rc=subprocess.run(cmd, cwd=ROOT).returncode
if rc!=0: fail("sim run failed")

sim=ROOT/"artifacts/sim_result.jsonl"; gold=ROOT/"golden/sim_result.jsonl"
if not sim.exists(): fail("sim output missing")
else:
    def norm(p): 
        return sorted([json.dumps(json.loads(x)) for x in p.read_text().splitlines() if x.strip()])
    if norm(sim)!=norm(gold): fail("golden mismatch")
    else: ok("golden match")

print("\nSUMMARY:", "PASS ✅" if FAIL==0 else "FAIL ❌"); sys.exit(FAIL)
