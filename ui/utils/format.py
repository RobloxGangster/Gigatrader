from __future__ import annotations
from typing import Any
from .num import to_float

def fmt_num(x: Any, digits: int = 2) -> str:
    v = to_float(x)
    return f"{v:,.{digits}f}" if isinstance(v, (int, float)) else str(x)

def fmt_currency(x: Any, digits: int = 2, symbol: str = "$") -> str:
    v = to_float(x)
    return f"{symbol}{v:,.{digits}f}" if isinstance(v, (int, float)) else str(x)

def fmt_signed_currency(x: Any, digits: int = 2, symbol: str = "$") -> str:
    v = to_float(x)
    return (f"+{symbol}{abs(v):,.{digits}f}" if v >= 0 else f"-{symbol}{abs(v):,.{digits}f}") if isinstance(v, (int, float)) else str(x)

def fmt_pct(x: Any, digits: int = 2) -> str:
    v = to_float(x)
    return f"{v*100:.{digits}f}%" if isinstance(v, (int, float)) else str(x)
