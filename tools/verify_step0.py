#!/usr/bin/env python3
"""Sanity checks for phase-0 requirements."""

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]


def die(msg: str) -> None:
    """Exit with failure."""
    print(f"FAIL: {msg}")
    sys.exit(1)


def ok(msg: str) -> None:
    """Print success message."""
    print(f"OK: {msg}")


def main() -> None:
    """Run verification steps."""
    # 1) required files
    req = [
        ".python-version",
        ".gitignore",
        "README.md",
        ".env.example",
        "Makefile",
        "requirements-core.in",
        "requirements-dev.in",
        "requirements-ui.in",
        "requirements-ml.in",
        "app/__init__.py",
        "app/init.py",
        "app/config.py",
        "app/rate_limit.py",
        "app/smoke/__init__.py",
        "app/smoke/paper_stream.py",
        "tests/__init__.py",
        "tests/init.py",
        "tests/test_config.py",
        "tests/test_rate_limit.py",
        ".github/workflows/ci.yml",
    ]
    missing = [p for p in req if not (ROOT / p).exists()]
    if missing:
        die("missing: " + ", ".join(missing))
    ok("files present")

    # 2) python pin
    py = (ROOT / ".python-version").read_text().strip()
    if not re.match(r"^3\.11\.\d+$", py):
        die(f".python-version not 3.11.x: {py}")
    ok(f"python pinned {py}")

    # 3) env example keys
    env = (ROOT / ".env.example").read_text()
    for key in [
        "ALPACA_API_KEY_ID",
        "ALPACA_API_SECRET_KEY",
        "ALPACA_PAPER",
        "ALPACA_DATA_FEED",
        "SMOKE_SYMBOLS",
        "SMOKE_TIMEFRAME",
    ]:
        if f"{key}=" not in env:
            die(f".env.example missing {key}")
    ok(".env.example schema ok")

    # 4) config accepts old/new names
    cfg = (ROOT / "app/config.py").read_text()
    if "ALPACA_API_KEY_ID" not in cfg or "ALPACA_API_SECRET_KEY" not in cfg:
        die("config lacks new var names")
    if "ALPACA_API_KEY" not in cfg or "ALPACA_API_SECRET" not in cfg:
        die("config lacks fallback var names")
    ok("config env fallbacks ok")

    # 5) ensure .env not tracked now
    if (ROOT / ".env").exists():
        print("WARN: local .env present (not tracked if .gitignore works).")
    ok("verify complete")


if __name__ == "__main__":
    main()
