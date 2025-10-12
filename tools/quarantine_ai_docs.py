#!/usr/bin/env python3
"""Relocate AI prompt/spec files into docs/agents with pointer stubs."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "docs" / "agents"
TARGET.mkdir(parents=True, exist_ok=True)

PATTERN = re.compile(r"(agent|prompt|instruction|codex|ai_spec)", re.IGNORECASE)
EXCLUDED_TOP_LEVEL = {".git", ".venv", "artifacts"}
POINTER_PREFIX = "Moved to docs/agents/"
SAFE_FILES = {Path("docs/codex-guardrails.md")}


def should_skip(path: Path) -> bool:
    """Return True when the file should not be processed."""
    rel_parts = path.relative_to(ROOT).parts
    if rel_parts and rel_parts[0] in EXCLUDED_TOP_LEVEL:
        return True
    if path.is_symlink() or not path.is_file():
        return True
    if path == ROOT:
        return True
    if TARGET in path.parents or path.parent == TARGET:
        return True
    rel_path = path.relative_to(ROOT)
    if rel_path in SAFE_FILES:
        return True
    if not PATTERN.search(str(rel_path)):
        return True
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False
    return text.startswith(POINTER_PREFIX)


def unique_destination(src: Path) -> Path:
    """Return a unique destination path within docs/agents/."""
    base = src.name
    dest = TARGET / base
    if not dest.exists():
        return dest
    stem = src.stem
    suffix = src.suffix
    counter = 1
    while True:
        candidate = TARGET / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def quarantine() -> list[tuple[Path, Path]]:
    moved: list[tuple[Path, Path]] = []
    for path in ROOT.rglob("*"):
        if should_skip(path):
            continue
        destination = unique_destination(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(destination))
        pointer = path
        pointer.parent.mkdir(parents=True, exist_ok=True)
        pointer.write_text(f"{POINTER_PREFIX}{destination.name}.\n", encoding="utf-8")
        moved.append((path, destination))
    return moved


if __name__ == "__main__":
    relocated = quarantine()
    print(f"Quarantined {len(relocated)} files to docs/agents/. OK")
