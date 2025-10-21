from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

router = APIRouter()


def _probe_logs() -> str:
    path = Path(os.getenv("APP_LOG_FILE", "logs/app.log"))
    if path.exists():
        return f"log available ({path})"
    return f"log file missing ({path})"


def _probe_env() -> str:
    keys = ["APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "APCA_API_BASE_URL"]
    present = [key for key in keys if os.getenv(key)]
    return f"alpaca_env={len(present)}/{len(keys)}"


@router.post("/run")
def diagnostics_run() -> Dict[str, Any]:
    """Lightweight self-check endpoint."""

    try:
        details: List[Dict[str, Any]] = []

        def _capture(name: str, func) -> None:
            try:
                details.append({"check": name, "ok": True, "detail": func()})
            except Exception as exc:  # pragma: no cover - defensive guard
                details.append({"check": name, "ok": False, "detail": str(exc)})

        _capture("uptime", lambda: f"started_at={time.time():.0f}")
        _capture("logs", _probe_logs)
        _capture("env", _probe_env)

        overall_ok = all(item.get("ok") for item in details)
        return {"ok": overall_ok, "message": "Diagnostics complete", "details": details}
    except Exception as exc:  # pragma: no cover - defensive guard
        raise HTTPException(500, f"diagnostics_run: {exc}") from exc
