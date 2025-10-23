#!/usr/bin/env python3
"""Quick check to verify Alpaca credentials are valid."""

from __future__ import annotations

import os
import sys
from typing import Any

import requests

BASE_URL = os.getenv("GIGATRADER_API", "http://127.0.0.1:8000").rstrip("/")


def main() -> int:
    try:
        response = requests.get(f"{BASE_URL}/broker/account", timeout=5)
    except Exception as exc:  # noqa: BLE001 - network errors surface as failures
        print(f"error: request failed: {exc}", file=sys.stderr)
        return 2

    if response.status_code == 401:
        print("error: unauthorized (check Alpaca keys)", file=sys.stderr)
        return 3

    if not response.ok:
        print(f"error: unexpected status {response.status_code}", file=sys.stderr)
        try:
            print(response.text, file=sys.stderr)
        except Exception:  # pragma: no cover - best effort
            pass
        return 4

    data: Any = response.json()
    equity = data.get("equity") if isinstance(data, dict) else None
    print(f"Broker equity: {equity}")
    return 0 if equity is not None else 5


if __name__ == "__main__":  # pragma: no cover - script entry point
    sys.exit(main())
