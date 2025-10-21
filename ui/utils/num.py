from __future__ import annotations

from decimal import Decimal

def to_float(x):
    if isinstance(x, Decimal):
        return float(x)
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(x)
    except Exception:
        return x
