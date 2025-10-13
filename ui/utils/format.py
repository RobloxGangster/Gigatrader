from __future__ import annotations
from typing import Any

from .num import to_float


def fmt_num(x: Any, digits: int = 2) -> str:
    v = to_float(x)
    if isinstance(v, (int, float)):
        return f"{v:,.{digits}f}"
    return str(x)


def fmt_currency(x: Any, digits: int = 2, symbol: str = "$") -> str:
    v = to_float(x)
    if isinstance(v, (int, float)):
        return f"{symbol}{v:,.{digits}f}"
    return str(x)


def fmt_signed_currency(x: Any, digits: int = 2, symbol: str = "$") -> str:
    v = to_float(x)
    if isinstance(v, (int, float)):
        sign = "+" if v >= 0 else "-"
        return f"{sign}{symbol}{abs(v):,.{digits}f}"
    return str(x)


def fmt_pct(x: Any, digits: int = 2) -> str:
    v = to_float(x)
    if isinstance(v, (int, float)):
        return f"{v*100:.{digits}f}%"
    return str(x)
