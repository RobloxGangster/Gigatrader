"""Streaming controls exposed to the UI."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from .deps import get_stream_manager

router = APIRouter()

def _normalize_status(status: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(status)
    payload.setdefault("running", bool(status.get("ok", True)))
    payload.setdefault("status", "online" if payload.get("running") else "stopped")
    if payload.get("last_heartbeat") is None:
        payload["last_heartbeat"] = None
    return payload


@router.get("/status")
async def stream_status() -> dict:
    sm = get_stream_manager()
    try:
        status = sm.status()
        if inspect.isawaitable(status):
            status = await status
        if isinstance(status, dict):
            return _normalize_status(status)
        return _normalize_status({"ok": bool(status), "running": bool(status)})
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=500, detail=f"stream_status: {exc}") from exc


@router.post("/start")
async def stream_start() -> dict:
    sm = get_stream_manager()
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        sm.start(loop)
        status = sm.status()
        if inspect.isawaitable(status):
            status = await status
        if isinstance(status, dict):
            return _normalize_status(status)
        return _normalize_status({"ok": bool(status), "running": True})
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=500, detail=f"stream_start: {exc}") from exc


@router.post("/stop")
async def stream_stop() -> dict:
    sm = get_stream_manager()
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        sm.stop(loop)
        status = sm.status()
        if inspect.isawaitable(status):
            status = await status
        if isinstance(status, dict):
            return _normalize_status(status)
        return _normalize_status({"ok": bool(status), "running": False})
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=500, detail=f"stream_stop: {exc}") from exc
