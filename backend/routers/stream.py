"""Streaming controls exposed to the UI."""

from __future__ import annotations

import asyncio
import inspect
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from .deps import get_stream_manager

router = APIRouter()

_STREAM_LAST_HEARTBEAT: float | None = None


def _format_ts(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _determine_source() -> str:
    source = os.getenv("MARKET_DATA_SOURCE", "").strip().lower()
    return "sip" if source in {"sip", "alpaca-sip"} else "mock"


def _status_payload(status: Dict[str, object], *, running: bool | None = None) -> Dict[str, object]:
    global _STREAM_LAST_HEARTBEAT
    inferred_running = running
    if inferred_running is None:
        inferred_running = status.get("status") in {"online", "connecting"}
    if status.get("status") == "online":
        _STREAM_LAST_HEARTBEAT = time.time()
    payload: Dict[str, Any] = {
        "running": bool(inferred_running),
        "last_heartbeat": _format_ts(_STREAM_LAST_HEARTBEAT),
        "source": _determine_source(),
    }
    if status.get("last_error"):
        payload["last_error"] = status["last_error"]
    return payload


@router.get("/status")
async def stream_status() -> dict:
    sm = get_stream_manager()
    try:
        status = sm.status()
        if inspect.isawaitable(status):
            status = await status
        return _status_payload(status)
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=500, detail=f"stream_status: {exc}") from exc


@router.post("/start")
def stream_start() -> dict:
    sm = get_stream_manager()
    try:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = None
        sm.start(loop)
        return _status_payload({"status": "online"}, running=True)
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=500, detail=f"stream_start: {exc}") from exc


@router.post("/stop")
def stream_stop() -> dict:
    sm = get_stream_manager()
    try:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = None
        sm.stop(loop)
        global _STREAM_LAST_HEARTBEAT
        _STREAM_LAST_HEARTBEAT = None
        return _status_payload({"status": "offline"}, running=False)
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=500, detail=f"stream_stop: {exc}") from exc
