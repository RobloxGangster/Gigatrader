"""Health check endpoint for the backend API."""

from __future__ import annotations

import os
from typing import Any, Dict

from fastapi import APIRouter, Depends

from backend.routers.deps import (
    get_broker_adapter,
    get_stream_manager,
)
from backend.services.orchestrator import get_orchestrator_status
from backend.services.stream_factory import StreamService
from core.runtime_flags import get_runtime_flags, parse_bool

router = APIRouter(tags=["health"])


def _paper_flag_from_env() -> bool:
    return parse_bool(os.getenv("ALPACA_USE_PAPER"), default=True)


@router.get("/health")
async def health(stream: StreamService = Depends(get_stream_manager)) -> Dict[str, Any]:
    """Return a tolerant health payload that never raises."""

    # IMPORTANT: This handler underpins the Streamlit Control Center, the
    # launcher script and automated smoke tests. It must *never* raise an
    # exception or trigger a 500 even when configuration is broken — always
    # surface errors in the JSON payload instead.

    flags = get_runtime_flags()

    broker_name = "unknown"
    broker_error: str | None = None
    broker_impl: str | None = None
    try:
        adapter = get_broker_adapter()
        broker_impl = type(adapter).__name__
        broker_name = getattr(adapter, "name", broker_impl)
    except Exception as exc:  # pragma: no cover - configuration failures
        broker_name = "error"
        broker_error = str(exc)
        adapter = None

    stream_info: Dict[str, Any]
    stream_source = "unknown"
    try:
        status_payload = await stream.status()
        if isinstance(status_payload, dict):
            stream_info = status_payload
            stream_source = str(status_payload.get("source", "unknown"))
        else:
            stream_info = {"status": status_payload, "ok": True}
    except Exception as exc:  # pragma: no cover - defensive guard
        stream_info = {"ok": False, "error": str(exc)}
        stream_source = f"error:{exc}"

    orch_snapshot: Dict[str, Any]
    try:
        orch_snapshot = get_orchestrator_status()
    except Exception as exc:  # pragma: no cover - defensive guard
        orch_snapshot = {"state": "unknown", "error": str(exc)}

    orchestrator_state = str(orch_snapshot.get("state", "stopped")).title()
    kill_label = orch_snapshot.get("kill_switch")
    if not isinstance(kill_label, str) or not kill_label:
        engaged = bool(orch_snapshot.get("kill_switch_engaged"))
        kill_label = "Triggered" if engaged else "Standby"

    ok = True
    if broker_error:
        ok = False
    if stream_source.startswith("error"):
        ok = False
    if kill_label == "Triggered":
        ok = False

    payload: Dict[str, Any] = {
        "ok": ok,
        "broker": broker_name,
        "broker_impl": broker_impl,
        "error": broker_error,
        "stream_source": stream_source,
        "stream": stream_info,
        "orchestrator_state": orchestrator_state,
        "orchestrator": orch_snapshot,
        "kill_switch": kill_label,
        "kill_switch_engaged": bool(orch_snapshot.get("kill_switch_engaged")),
        "mock_mode": bool(getattr(flags, "mock_mode", False)),
        "dry_run": bool(getattr(flags, "dry_run", False)),
        "profile": getattr(flags, "profile", "paper"),
        "paper_mode": bool(getattr(flags, "paper_trading", True)),
        "alpaca_use_paper": _paper_flag_from_env(),
    }

    if adapter is not None:
        payload["broker_headers"] = getattr(adapter, "last_headers", None)

    return payload
