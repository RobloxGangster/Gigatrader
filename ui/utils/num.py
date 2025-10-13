from __future__ import annotations

from decimal import Decimal
from typing import Any


def to_float(x: Any):
    if isinstance(x, Decimal):
        return float(x)
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(x)
    except Exception:
        return x  # let caller decide; safe for strings
