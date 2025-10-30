from __future__ import annotations

import logging
import threading
import time
import traceback
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Literal, Optional

from core.kill_switch import KillSwitch
from core.market_hours import market_is_open

log = logging.getLogger(__name__)


OrchestratorState = Literal[
    "stopped",
    "starting",
    "running",
    "stopping",
    "crashed",
    "error_startup",
    "idle",
    "waiting_market_open",
]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(ts: datetime | None) -> str | None:
    if ts is None:
        return None
    return ts.isoformat().replace("+00:00", "Z")


class OrchestratorManager:
    """Run the trading orchestrator inside a dedicated background thread."""

    def __init__(self) -> None:
        self._state: OrchestratorState = "stopped"
        self._thread: Optional[threading.Thread] = None
        self._stop_flag: bool = False
        self._last_error: Optional[str] = None
        self._last_error_stack: Optional[str] = None
        self._start_attempt_ts: Optional[datetime] = None
        self._thread_started_at: Optional[datetime] = None
        self._last_stop_ts: Optional[datetime] = None
        self._last_exit_reason: Optional[str] = None
        self._lock = threading.Lock()
        self._watchdog_thread: Optional[threading.Thread] = None
        self._watchdog_stop = threading.Event()
        self._entrypoint: Optional[Callable[[Callable[[], bool]], None]] = None
        self._auto_restart_enabled = False
        self._restart_count = 0
        self._kill_switch = KillSwitch()

    def get_status(self) -> Dict[str, Any]:
        """Return a lightweight snapshot about the orchestrator thread."""

        with self._lock:
            thread_alive = self._thread.is_alive() if self._thread else False
            return {
                "state": self._state,
                "last_error": self._last_error,
                "last_error_stack": self._last_error_stack,
                "thread_alive": thread_alive,
                "start_attempt_ts": _iso(self._start_attempt_ts),
                "thread_started_at": _iso(self._thread_started_at),
                "last_stop_ts": _iso(self._last_stop_ts),
                "last_exit_reason": self._last_exit_reason,
                "restart_count": self._restart_count,
            }

    def start(self, trading_entrypoint: Callable[[Callable[[], bool]], None]) -> None:
        """Start the orchestrator thread if it is not already running."""

        with self._lock:
            if self._thread and self._thread.is_alive():
                if self._state in ("running", "starting"):
                    log.debug("orchestrator_manager.start skipped; thread already running")
                    return
            self._stop_flag = False
            self._state = "starting"
            self._last_error = None
            self._last_error_stack = None
            self._last_exit_reason = None
            self._last_stop_ts = None
            self._start_attempt_ts = _utc_now()
            self._entrypoint = trading_entrypoint
            self._auto_restart_enabled = True
            self._restart_count = 0
            log.info(
                "orchestrator_manager.start requested",
                extra={"start_attempt": _iso(self._start_attempt_ts)},
            )
            self._ensure_watchdog_locked()
            self._launch_thread_locked(trading_entrypoint)

    def stop(self) -> None:
        """Signal the orchestrator thread to stop gracefully."""

        with self._lock:
            thread = self._thread
            if not thread or not thread.is_alive():
                self._state = "stopped"
                self._stop_flag = False
                self._auto_restart_enabled = False
                self._entrypoint = None
                return
            if self._state not in ("running", "starting"):
                return
            self._stop_flag = True
            self._state = "stopping"
            self._auto_restart_enabled = False
            self._entrypoint = None
        if thread and thread.is_alive():
            log.info("orchestrator_manager.stop waiting for thread to exit")
            thread.join(timeout=10.0)
        with self._lock:
            still_alive = bool(thread and thread.is_alive())
            if still_alive:
                log.warning("orchestrator_manager.stop timeout waiting for thread")
            else:
                self._state = "stopped"
                self._stop_flag = False
                self._last_stop_ts = _utc_now()
                self._thread = None

    def _launch_thread_locked(
        self,
        trading_entrypoint: Callable[[Callable[[], bool]], None],
    ) -> None:
        def _runner() -> None:
            log.info("orchestrator_manager.thread.starting")
            try:
                with self._lock:
                    self._state = "running"
                    self._thread_started_at = _utc_now()
                trading_entrypoint(lambda: self._stop_flag)
                with self._lock:
                    exit_reason = "stop_requested" if self._stop_flag else "completed"
                    self._last_exit_reason = exit_reason
                    if self._stop_flag:
                        self._state = "stopped"
                    else:
                        self._state = (
                            "idle" if market_is_open() else "waiting_market_open"
                        )
            except Exception as exc:  # pragma: no cover - runtime defensive
                stack = traceback.format_exc()
                log.exception("orchestrator_manager.thread.crashed")
                with self._lock:
                    self._last_error = str(exc)
                    self._last_error_stack = stack
                    if self._state == "starting":
                        self._state = "error_startup"
                    else:
                        self._state = "crashed"
                    self._last_exit_reason = "exception"
            finally:
                with self._lock:
                    self._thread = None
                    self._stop_flag = False
                    self._last_stop_ts = _utc_now()
                    self._thread_started_at = None
                log.info(
                    "orchestrator_manager.thread.finished",
                    extra={
                        "state": self._state,
                        "last_exit_reason": self._last_exit_reason,
                    },
                )

        thread = threading.Thread(
            target=_runner,
            name="orchestrator-thread",
            daemon=True,
        )
        self._thread = thread
        thread.start()

    def _ensure_watchdog_locked(self) -> None:
        if self._watchdog_thread and self._watchdog_thread.is_alive():
            return
        self._watchdog_stop.clear()
        thread = threading.Thread(
            target=self._watchdog_loop,
            name="orchestrator-watchdog",
            daemon=True,
        )
        self._watchdog_thread = thread
        thread.start()

    def _watchdog_loop(self) -> None:
        while not self._watchdog_stop.is_set():
            if self._watchdog_stop.wait(timeout=1.5):
                break
            with self._lock:
                entrypoint = self._entrypoint
                thread = self._thread
                stop_flag = self._stop_flag
                auto_restart = self._auto_restart_enabled
                state = self._state
            if not auto_restart or entrypoint is None:
                continue
            if thread is not None and thread.is_alive():
                continue
            if stop_flag:
                continue
            if self._kill_switch.engaged_sync():
                continue
            log.warning(
                "orchestrator_manager.watchdog.restart", extra={"state": state}
            )
            with self._lock:
                if not self._auto_restart_enabled or self._entrypoint is None:
                    continue
                self._restart_count += 1
                self._state = "starting"
                self._last_error = None
                self._last_error_stack = None
                entry = self._entrypoint
            if entry is None:
                continue
            self._launch_thread_locked(entry)
            time.sleep(0.1)


orchestrator_manager = OrchestratorManager()

__all__ = ["OrchestratorManager", "OrchestratorState", "orchestrator_manager"]
