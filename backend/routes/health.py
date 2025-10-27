"""Health check endpoint for the backend API."""

from __future__ import annotations

import inspect
import os
from typing import Any

from fastapi import APIRouter, Depends

from backend.routers.deps import BrokerService, get_broker
from backend.services.stream_factory import StreamService, make_stream_service
from core.runtime_flags import get_runtime_flags


router = APIRouter(tags=["health"])


def _is_mock() -> bool:
    return get_runtime_flags().mock_mode


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


@router.get("/health")
async def health(
    stream: StreamService = Depends(make_stream_service),
    broker: BrokerService = Depends(get_broker),
) -> dict[str, Any]:
    stream_status = await _maybe_await(stream.status())

    broker_ok = True
    try:
        if hasattr(broker, "ping"):
            await _maybe_await(broker.ping())
    except Exception:  # pragma: no cover - defensive ping guard
        broker_ok = False

    payload: dict[str, Any] = {
        "status": "ok",
        "mock_mode": _is_mock(),
        "version": os.getenv("APP_VERSION", "dev"),
        "stream": stream_status,
        "broker_ok": broker_ok,
    }
    if isinstance(stream_status, dict) and "healthy" in stream_status:
        payload["stream_ok"] = bool(stream_status.get("healthy"))
    return payload
