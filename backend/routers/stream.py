"""Streaming controls exposed to the UI."""

import asyncio

from fastapi import APIRouter, HTTPException

from .deps import get_stream_manager

router = APIRouter()


@router.get("/stream/status")
def stream_status() -> dict:
    sm = get_stream_manager()
    try:
        return sm.status()
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=500, detail=f"stream_status: {exc}") from exc


@router.post("/stream/start")
def stream_start() -> dict:
    sm = get_stream_manager()
    try:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = None
        sm.start(loop)
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=500, detail=f"stream_start: {exc}") from exc


@router.post("/stream/stop")
def stream_stop() -> dict:
    sm = get_stream_manager()
    try:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = None
        sm.stop(loop)
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=500, detail=f"stream_stop: {exc}") from exc
