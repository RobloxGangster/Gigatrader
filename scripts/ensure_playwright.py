"""Ensure Playwright browsers are installed for local and CI runs."""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    try:
        import playwright  # noqa: F401
    except Exception:  # pragma: no cover - import guard
        return 0

    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "playwright",
                "install",
                "chromium",
                "--with-deps",
            ],
            check=True,
        )
    except Exception:  # pragma: no cover - setup helper
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - script entrypoint
    raise SystemExit(main())
