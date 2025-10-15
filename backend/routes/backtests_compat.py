from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pathlib import Path
import json

router = APIRouter(tags=["backtests"])

_BASE = Path("artifacts") / "backtests"


@router.get("/backtests")
def list_backtests():
    """
    Returns a list of backtest runs with minimal fields used by the UI.
    Looks for artifacts/backtests/index.json; falls back to scanning directories.
    """
    idx = _BASE / "index.json"
    if idx.exists():
        try:
            return json.loads(idx.read_text(encoding="utf-8"))
        except Exception:
            return []
    if not _BASE.exists():
        return []
    out = []
    for p in sorted(_BASE.iterdir()):
        if p.is_dir():
            meta = p / "summary.json"
            if meta.exists():
                try:
                    data = json.loads(meta.read_text(encoding="utf-8"))
                    out.append({"run_id": p.name, **data})
                except Exception:
                    out.append({"run_id": p.name})
            else:
                out.append({"run_id": p.name})
    return out


@router.get("/backtests/{run_id}")
def get_backtest(run_id: str):
    meta = _BASE / run_id / "summary.json"
    if meta.exists():
        try:
            return json.loads(meta.read_text(encoding="utf-8"))
        except Exception as e:
            raise HTTPException(500, f"Corrupt report: {e}") from e
    raise HTTPException(404, f"Backtest '{run_id}' not found")
