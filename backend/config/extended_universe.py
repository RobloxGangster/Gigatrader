from __future__ import annotations
from pathlib import Path
from typing import List, Set
import os
from zoneinfo import ZoneInfo
from datetime import datetime, time

_DEFAULT_FILE = os.getenv("EXTENDED_UNIVERSE_FILE", "config/extended_tickers.txt")

def load_extended_tickers(path: str | None = None) -> List[str]:
    p = Path(path or _DEFAULT_FILE)
    if not p.exists():
        return []
    syms: List[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip().upper()
        if s and not s.startswith("#"):
            syms.append(s)
    # de-dup but keep order
    seen: Set[str] = set()
    out: List[str] = []
    for s in syms:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out

def is_rth(now: datetime | None = None) -> bool:
    """Regular Trading Hours: 9:30–16:00 ET, Mon–Fri (no holiday logic here)."""
    et = (now or datetime.utcnow()).astimezone(ZoneInfo("America/New_York"))
    wd = et.weekday()  # 0 Mon .. 4 Fri
    if wd > 4:
        return False
    t = et.time()
    return time(9, 30) <= t < time(16, 0)

def is_extended(now: datetime | None = None) -> bool:
    """
    Alpaca extended hours: pre (04:00–09:30), after (16:00–20:00), overnight (20:00–04:00) ET.
    Ref: docs (Extended Hours Trading), OPG at the open.  :contentReference[oaicite:3]{index=3}
    """
    et = (now or datetime.utcnow()).astimezone(ZoneInfo("America/New_York"))
    t = et.time()
    if is_rth(et):
        return False
    # Overnight 20:00–24:00 or 00:00–04:00
    if time(20, 0) <= t or t < time(4, 0):
        return True
    # Pre 04:00–09:30
    if time(4, 0) <= t < time(9, 30):
        return True
    # After 16:00–20:00
    if time(16, 0) <= t < time(20, 0):
        return True
    return False
