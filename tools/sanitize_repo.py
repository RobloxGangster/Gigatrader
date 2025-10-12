#!/usr/bin/env python3
import os, re, sys, argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

KEEP_MD_BASENAMES = {
  "README.md","CONTRIBUTING.md","LICENSE","LICENSE.md","LICENSE.txt",
  "SECURITY.md","CODE_OF_CONDUCT.md","CHANGELOG.md"
}

# Directories whose *.md we always keep (docs), except agent pointer stubs we’ll clean.
KEEP_MD_DIRS = {"docs"}
# Directories that often contain non-source artifacts we may prune.
PRUNE_TXT_DIRS = {"reports","artifacts","tmp","temp","notes","notebooks"}

# Regex to detect one-line pointer stubs (case-insensitive), e.g. "Moved to docs/agents/foo.md"
POINTER_RE = re.compile(r"^\s*(moved to|moved|see|relocated to)\s+docs/agents/.*", re.I)

# *.txt allowlist (never delete)
KEEP_TXT_PATTERNS = [
  re.compile(r"^requirements-.*\.txt$", re.I),   # pip-tools lockfiles
  re.compile(r"^LICENSE(\.txt)?$", re.I),
  re.compile(r"^NOTICE(\.txt)?$", re.I),
  re.compile(r".*golden.*\.txt$", re.I),         # golden fixtures (if any)
]

# Paths we never touch
PROTECT_DIRS = {".git",".venv","venv",".github","__pycache__"}

def is_pointer_stub(path: Path) -> bool:
  try:
    text = path.read_text(encoding="utf-8", errors="ignore")
  except Exception:
    return False
  # Only short files likely to be stubs
  if len(text) > 2000: 
    return False
  return bool(POINTER_RE.search(text.strip().splitlines()[0] if text.strip() else ""))

def is_keep_md(path: Path) -> bool:
  if path.name in KEEP_MD_BASENAMES: return True
  # allow docs/**/*.md (except agent pointer stubs)
  if any(part == "docs" for part in path.parts):
    # if under docs/agents and looks like a pointer stub, mark removable
    if "docs" in path.parts and "agents" in path.parts:
      return not is_pointer_stub(path)
    return True
  return False

def is_keep_txt(path: Path) -> bool:
  name = path.name
  for rx in KEEP_TXT_PATTERNS:
    if rx.match(name): return True
  return False

def should_delete_md(path: Path) -> bool:
  # delete .md outside docs/ unless in KEEP list, and delete docs/agents pointer stubs
  if any(part in PROTECT_DIRS for part in path.parts): return False
  if is_keep_md(path): return False
  # Permit deletion of top-level or nested random *.md (design notes, scratch)
  # Also delete pointer stubs anywhere
  if is_pointer_stub(path): return True
  # Non-essential *.md outside docs
  return True

def should_delete_txt(path: Path) -> bool:
  if any(part in PROTECT_DIRS for part in path.parts): return False
  if is_keep_txt(path): return False
  # Preserve well-known data/test areas
  if any(part in {"data","golden","tests","test","fixtures"} for part in path.parts):
    return False
  # Delete *.txt in known artifact dirs or at root if it looks like notes/logs
  if path.suffix.lower() == ".txt":
    # prefer pruning only in non-source dirs
    if any(d in PRUNE_TXT_DIRS for d in path.parts):
      return True
    # Heuristic: kill obvious exports/logs/scratch at root or misc dirs
    lower = path.name.lower()
    if any(token in lower for token in ["notes","todo","log","output","export","dump"]):
      return True
  return False

def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--dry-run", default=os.getenv("DRY_RUN","1")!="0", action="store_true")
  ap.add_argument("--no-dry-run", dest="dry_run", action="store_false")
  args = ap.parse_args()

  to_delete = []
  for p in ROOT.rglob("*"):
    if p.is_dir(): continue
    # Skip binary or huge files quickly
    try:
      if p.suffix.lower() == ".md":
        if should_delete_md(p): to_delete.append(p)
      elif p.suffix.lower() == ".txt":
        if should_delete_txt(p): to_delete.append(p)
    except Exception:
      continue

  print(f"[sanitize] Candidates: {len(to_delete)}")
  for f in to_delete:
    print("DELETE", f.relative_to(ROOT))

  if args.dry_run:
    print("[sanitize] Dry-run only (no files deleted). To apply: DRY_RUN=0 python tools/sanitize_repo.py")
    return

  deleted = 0
  for f in to_delete:
    try:
      f.unlink()
      deleted += 1
    except FileNotFoundError:
      pass
  print(f"[sanitize] Deleted: {deleted}")

if __name__ == "__main__":
  main()
