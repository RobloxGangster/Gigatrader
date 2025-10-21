from __future__ import annotations
import pathlib
import re

# Fix placement of `from __future__ import annotations` for UI modules
ROOTS = [pathlib.Path("ui/pages"), pathlib.Path("ui")]

FUTURE_LINE = "from __future__ import annotations\n"

TRIPLE_START = re.compile(r'\s*(?:[rRuUfF]{0,2})("""|\'\'\')')
FUTURE_RX = re.compile(r"\s*from\s+__future__\s+import\s+annotations\s*$")

def _find_docstring_end(lines: list[str], i: int) -> int:
    """Return index after a top-level triple-quoted docstring, else i."""
    if i >= len(lines):
        return i
    m = TRIPLE_START.match(lines[i])
    if not m:
        return i
    delim = m.group(1)
    i += 1
    while i < len(lines):
        if delim in lines[i]:
            return i + 1
        i += 1
    return i


def _insert_point(lines: list[str]) -> int:
    """Index where the future import should be inserted."""
    i = 0
    # skip shebang/encoding
    while i < len(lines) and (lines[i].startswith("#!") or "coding" in lines[i]):
        i += 1
    # skip leading comments/blank lines
    while i < len(lines) and (lines[i].strip().startswith("#") or not lines[i].strip()):
        i += 1
    # skip module docstring
    i = _find_docstring_end(lines, i)
    # also skip following blank lines
    while i < len(lines) and not lines[i].strip():
        i += 1
    return i


def fix_file(p: pathlib.Path) -> bool:
    if p.suffix != ".py":
        return False
    text = p.read_text(encoding="utf-8")
    if "from __future__ import annotations" not in text:
        return False

    lines = text.splitlines(keepends=True)
    kept: list[str] = []
    removed = False
    for ln in lines:
        if FUTURE_RX.match(ln):
            removed = True
            continue
        kept.append(ln)
    if not removed:
        return False

    idx = _insert_point(kept)
    kept.insert(idx, FUTURE_LINE)
    p.write_text("".join(kept), encoding="utf-8")
    return True


def main() -> None:
    changed = 0
    for root in ROOTS:
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            if fix_file(p):
                changed += 1
    print(f"Moved future import in {changed} files.")


if __name__ == "__main__":
    main()
