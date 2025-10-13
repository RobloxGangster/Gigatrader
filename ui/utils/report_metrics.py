from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from typing import Any, Iterable, Optional


def get_field(obj: Any, names: Iterable[str], default: Any = None) -> Any:
    """Try multiple attribute/key names on a Pydantic model or dict-like."""
    for name in names:
        if hasattr(obj, name):
            val = getattr(obj, name)
            if val is not None:
                return val
        if isinstance(obj, dict) and name in obj and obj[name] is not None:
            return obj[name]
        if isinstance(obj, Mapping) and name in obj and obj[name] is not None:
            return obj[name]
        if hasattr(obj, "get"):
            try:
                value = obj.get(name)
            except Exception:  # pragma: no cover
                value = None
            if value is not None:
                return value
        if hasattr(obj, "model_dump"):
            try:
                data = obj.model_dump(exclude_none=True)
            except Exception:  # pragma: no cover - guard against unexpected implementations
                data = None
            if data and name in data:
                return data[name]
        if hasattr(obj, "dict"):
            try:
                data = obj.dict(exclude_none=True)
            except Exception:  # pragma: no cover
                data = None
            if data and name in data:
                return data[name]
    return default


def compute_cagr_from_return(total_return_decimal: float, days: float) -> Optional[float]:
    """Compute CAGR from total return expressed as decimal and duration in days."""
    try:
        if days and isfinite(days) and days > 0:
            years = days / 365.0
            if years > 0:
                return (1.0 + float(total_return_decimal)) ** (1.0 / years) - 1.0
    except Exception:
        pass
    return None


def compute_cagr_from_equity(first: float, last: float, days: float) -> Optional[float]:
    try:
        if all(isfinite(x) for x in (first, last, days)) and first > 0 and days > 0:
            total_return = (last / first) - 1.0
            return compute_cagr_from_return(total_return, days)
    except Exception:
        pass
    return None
