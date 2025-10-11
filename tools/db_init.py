#!/usr/bin/env python3
"""CLI helper to ensure TimescaleDB schema is created."""

from __future__ import annotations

import os

from services.market.store import TSStore


def main() -> None:
    url = os.getenv("TIMESCALE_URL", "")
    if not url:
        raise SystemExit("TIMESCALE_URL is required")
    TSStore(url)
    print("Timescale schema ensured.")


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
