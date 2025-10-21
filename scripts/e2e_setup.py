"""Ensure Playwright browsers are installed for E2E runs."""

from __future__ import annotations

from scripts.ensure_playwright import main as ensure_playwright


def main() -> int:
    ensure_playwright()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
