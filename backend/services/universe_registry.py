from __future__ import annotations
from typing import List, Sequence
import threading

_lock = threading.RLock()
_override: List[str] = []

def set_override_universe(symbols: Sequence[str]) -> None:
    syms = [s.strip().upper() for s in symbols if str(s).strip()]
    with _lock:
        _override.clear()
        _override.extend(syms)

def get_override_universe() -> List[str]:
    with _lock:
        return list(_override)

def clear_override_universe() -> None:
    with _lock:
        _override.clear()
