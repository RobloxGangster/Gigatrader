"""Threaded orchestrator manager with idempotent transitions."""

from __future__ import annotations

import logging
import threading
import traceback
from datetime import datetime, timezone
from typing import Any, Callable, Dict

from backend.models.orchestrator import OrchestratorStatus


log = logging.getLogger(__name__)


_state = OrchestratorStatus()
_lock = threading.Lock()
_worker_thread: threading.Thread | None = None
_stop_event = threading.Event()
_thread_started_at: datetime | None = None
_last_error_stack: str | None = None
_last_error_at: datetime | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _snapshot_locked() -> Dict[str, Any]:
    thread_alive = bool(_worker_thread and _worker_thread.is_alive())
    uptime = 0.0
    if thread_alive and _thread_started_at:
        uptime = max(0.0, (_utcnow() - _thread_started_at).total_seconds())
    snapshot = _state.model_copy(update={
        "thread_alive": thread_alive,
        "uptime_secs": uptime,
        "last_error_stack": _last_error_stack,
        "last_error_at": _last_error_at,
    })
    return snapshot.model_dump()


def _update_state(**kwargs: Any) -> None:
    for key, value in kwargs.items():
        setattr(_state, key, value)


def start(trading_entrypoint: Callable[[Callable[[], bool]], None]) -> Dict[str, Any]:
    """Start the orchestrator thread if not already running."""

    global _worker_thread, _thread_started_at, _last_error_stack, _last_error_at

    with _lock:
        thread_alive = bool(_worker_thread and _worker_thread.is_alive())
        if thread_alive and _state.state in {"starting", "running"}:
            return _snapshot_locked()
        if thread_alive:
            # Thread is alive but not marked running; avoid double-spawn.
            return _snapshot_locked()

        _stop_event.clear()
        _update_state(
            state="starting",
            running=True,
            last_error=None,
            start_attempt_ts=_utcnow(),
            last_shutdown_reason=None,
        )
        _last_error_stack = None
        _last_error_at = None

        def _runner() -> None:
            nonlocal trading_entrypoint
            global _worker_thread, _thread_started_at, _last_error_stack, _last_error_at
            try:
                with _lock:
                    _update_state(state="running", running=True)
                    _state.restart_count += 1
                    _thread_started_at = _utcnow()
                trading_entrypoint(lambda: _stop_event.is_set())
            except Exception as exc:  # pragma: no cover - runtime guard
                stack = traceback.format_exc()
                log.exception("orchestrator_manager.worker.crashed")
                with _lock:
                    _update_state(last_error=str(exc))
                    _last_error_stack = stack
                    _last_error_at = _utcnow()
            finally:
                with _lock:
                    _update_state(state="stopped", running=False)
                    _thread_started_at = None
                    if _state.last_shutdown_reason is None:
                        _state.last_shutdown_reason = (
                            "requested_stop" if _stop_event.is_set() else "completed"
                        )
                    _worker_thread = None
                _stop_event.clear()

        thread = threading.Thread(target=_runner, name="orchestrator", daemon=True)
        _worker_thread = thread
        thread.start()
        return _snapshot_locked()


def stop(reason: str = "requested_stop") -> Dict[str, Any]:
    """Signal the orchestrator thread to stop, idempotently."""

    with _lock:
        if _state.state in {"stopping", "stopped"}:
            if reason and not _state.last_shutdown_reason:
                _state.last_shutdown_reason = reason
            _state.running = False
            return _snapshot_locked()

        _update_state(state="stopping", running=False)
        if reason:
            _state.last_shutdown_reason = reason
        _stop_event.set()
        return _snapshot_locked()


def status() -> Dict[str, Any]:
    """Return the current orchestrator status snapshot."""

    with _lock:
        return _snapshot_locked()


class OrchestratorManager:
    """Object wrapper exposing the manager operations."""

    def start(self, trading_entrypoint: Callable[[Callable[[], bool]], None]) -> Dict[str, Any]:
        return start(trading_entrypoint)

    def stop(self, reason: str = "requested_stop") -> Dict[str, Any]:
        return stop(reason)

    def get_status(self) -> Dict[str, Any]:
        return status()


orchestrator_manager = OrchestratorManager()


__all__ = ["orchestrator_manager", "OrchestratorManager", "start", "stop", "status"]

