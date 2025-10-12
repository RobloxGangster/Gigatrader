#!/usr/bin/env python3
from pathlib import Path
import shutil, sys

ROOT = Path(__file__).resolve().parents[1]
candidates = []
for p in ROOT.rglob("alpaca"):
    # skip site-packages and venvs
    if any(part in {".venv","venv","site-packages",".git"} for part in p.parts):
        continue
    # treat exact name 'alpaca' file or dir as shadowing
    if p.name == "alpaca":
        candidates.append(p)

renamed = []
for p in candidates:
    newp = p.with_name(p.name + "_local")
    if not newp.exists():
        p.rename(newp)
        renamed.append((p, newp))

print("RENAMED:", [str(x[0].relative_to(ROOT)) + " -> " + str(x[1].relative_to(ROOT)) for x in renamed])
