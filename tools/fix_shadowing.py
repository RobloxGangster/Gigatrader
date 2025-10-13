#!/usr/bin/env python3
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
ren=[]
for p in list(ROOT.rglob("alpaca")):
    if any(t in p.parts for t in (".venv","venv","site-packages",".git")): continue
    if p.name=="alpaca":
        np=p.with_name("alpaca_local")
        if not np.exists():
            p.rename(np); ren.append((p,np))
print("RENAMED:", [f"{a} -> {b}" for a,b in ren])
