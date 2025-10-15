from __future__ import annotations

from fastapi import APIRouter, Query
from typing import List, Optional, Dict, Any
from pathlib import Path
import json
import itertools

router = APIRouter(tags=["logs"])

_LOG_PATH = Path("runtime") / "logs.ndjson"


@router.get("/logs")
def logs_tail(tail: int = Query(200, ge=1, le=5000), level: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Returns a list of log events (most recent last). Each line is NDJSON.
    Optional level filter (case-insensitive contains).
    """
    if not _LOG_PATH.exists():
        return []
    lines = _LOG_PATH.read_text(encoding="utf-8").splitlines()
    last = list(itertools.islice(lines, max(0, len(lines) - tail), len(lines)))
    out = []
    for ln in last:
        try:
            evt = json.loads(ln)
            if level and level.lower() not in str(evt.get("level", "")).lower():
                continue
            out.append(evt)
        except Exception:
            continue

    _UI_DIAG = Path("logs") / "ui_diagnostics.ndjson"
    if _UI_DIAG.exists():
        try:
            diag_lines = _UI_DIAG.read_text(encoding="utf-8").splitlines()
            for ln in diag_lines[-tail:]:
                try:
                    evt = json.loads(ln)
                    out.append(evt)
                except Exception:
                    continue
        except Exception:
            pass

    # optional: sort by timestamp when present
    def _ts(e):
        return e.get("timestamp") or e.get("summary", {}).get("timestamp") or ""

    out.sort(key=_ts)
    return out
