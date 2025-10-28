from __future__ import annotations

import threading
from typing import Any, Callable, Dict, Literal, Optional

OrchestratorState = Literal["stopped", "starting", "running", "stopping", "error"]


class OrchestratorManager:
    """Run the trading orchestrator inside a dedicated background thread."""

    def __init__(self) -> None:
        self._state: OrchestratorState = "stopped"
        self._thread: Optional[threading.Thread] = None
        self._stop_flag: bool = False
        self._last_error: Optional[str] = None
        self._lock = threading.Lock()

    def get_status(self) -> Dict[str, Any]:
        """Return a lightweight snapshot about the orchestrator thread."""

        with self._lock:
            thread_alive = self._thread.is_alive() if self._thread else False
            return {
                "state": self._state,
                "last_error": self._last_error,
                "thread_alive": thread_alive,
            }

    def start(self, trading_entrypoint: Callable[[Callable[[], bool]], None]) -> None:
        """Start the orchestrator thread if it is not already running."""

        with self._lock:
            if self._thread and self._thread.is_alive():
                if self._state in ("running", "starting"):
                    return
            self._stop_flag = False
            self._state = "starting"
            self._last_error = None

            def _runner() -> None:
                try:
                    with self._lock:
                        self._state = "running"
                    trading_entrypoint(lambda: self._stop_flag)
                    with self._lock:
                        self._state = "stopped"
                except Exception as exc:  # pragma: no cover - runtime defensive
                    with self._lock:
                        self._last_error = str(exc)
                        self._state = "error"
                finally:
                    with self._lock:
                        self._thread = None
                        self._stop_flag = False

            thread = threading.Thread(
                target=_runner,
                name="orchestrator-thread",
                daemon=True,
            )
            self._thread = thread
            thread.start()

    def stop(self) -> None:
        """Signal the orchestrator thread to stop gracefully."""

        with self._lock:
            if self._state not in ("running", "starting"):
                return
            self._stop_flag = True
            self._state = "stopping"
            thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=0.0)


orchestrator_manager = OrchestratorManager()

__all__ = ["OrchestratorManager", "OrchestratorState", "orchestrator_manager"]
