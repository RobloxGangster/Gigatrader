"""Ensure Playwright browsers are installed for E2E runs."""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    try:
        import playwright  # noqa: F401
    except Exception as exc:  # pragma: no cover - import guard
        print(
            "Playwright Python package not available; install skipped. "
            f"({exc})"
        )
        return 0

    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
        )
    except Exception as exc:  # pragma: no cover - setup helper
        print(f"Failed to install Playwright browsers: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
