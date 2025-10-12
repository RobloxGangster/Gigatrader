#!/usr/bin/env python3
import hashlib, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
seen = {}
dups = []
IGNORE_DIRS = [Path(".git"), Path(".venv"), Path("artifacts")]
IGNORE_NAMES = {"__init__.py", "config.yaml", "config.example.yaml"}


def skip(p: Path):
    if p.suffix == ".pyc":
        return True
    if p.name in IGNORE_NAMES:
        return True
    for d in IGNORE_DIRS:
        if str(p).startswith(str(ROOT / d)):
            return True
    return False


for p in ROOT.rglob("*"):
    if not p.is_file():
        continue
    if skip(p):
        continue
    h = hashlib.sha1(p.read_bytes()).hexdigest()
    if h in seen:
        other = seen[h]
        if skip(other):
            continue
        dups.append((str(p.relative_to(ROOT)), str(other.relative_to(ROOT))))
    else:
        seen[h] = p
if dups:
    print("DUPLICATES:")
    for a, b in dups:
        print(f"{a} == {b}")
    sys.exit(1)
print("NO DUPS")
