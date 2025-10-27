from __future__ import annotations

import asyncio
import logging
import traceback
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any, Dict

from core.kill_switch import KillSwitch
from core.runtime_flags import runtime_flags_from_env


_CURRENT_SUPERVISOR: "OrchestratorSupervisor" | None = None
_last_order_attempt: Dict[str, Any] = {
    "ts": None,
    "symbol": None,
    "qty": None,
    "side": None,
    "sent": False,
    "accepted": False,
    "reason": None,
    "broker_impl": None,
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def record_order_attempt(
    *,
    symbol: str | None,
    qty: Any,
    side: str | None,
    sent: bool,
    accepted: bool,
    reason: str | None,
    broker_impl: str | None,
) -> None:
    global _last_order_attempt
    _last_order_attempt = {
        "ts": _iso_now(),
        "symbol": symbol,
        "qty": qty,
        "side": side,
        "sent": sent,
        "accepted": accepted,
        "reason": reason,
        "broker_impl": broker_impl,
    }


def get_last_order_attempt() -> Dict[str, Any]:
    return dict(_last_order_attempt)


def can_execute_trade(flags, kill_switch_engaged: bool) -> tuple[bool, str | None]:
    if kill_switch_engaged:
        return False, "kill_switch_engaged"
    if getattr(flags, "dry_run", False):
        return False, "dry_run_enabled"
    if getattr(flags, "mock_mode", False):
        return True, None
    broker = getattr(flags, "broker", "mock")
    if str(broker).lower() != "alpaca":
        return False, f"unsupported_broker:{broker}"
    profile = str(getattr(flags, "profile", "paper")).lower()
    if profile not in {"paper", "live"}:
        return False, f"unsupported_profile:{profile}"
    return True, None

log = logging.getLogger(__name__)


class OrchestratorSupervisor:
    """Supervise the trading runtime and restart it on failures."""

    def __init__(self, kill_switch: KillSwitch) -> None:
        self._kill_switch = kill_switch
        self._state: str = "stopped"
        self._async_lock = asyncio.Lock()
        self._supervisor_task: asyncio.Task[None] | None = None
        self._stop_requested = False
        self._last_error: str | None = None
        self._last_error_stack: str | None = None
        self._last_heartbeat: datetime | None = None
        self._start_time: datetime | None = None
        self._restart_count = 0
        global _CURRENT_SUPERVISOR
        _CURRENT_SUPERVISOR = self

    def status(self) -> dict[str, Any]:
        """Return a thread-safe status snapshot."""

        last_error = self._last_error_stack or self._last_error
        heartbeat = (
            self._last_heartbeat.isoformat()
            if isinstance(self._last_heartbeat, datetime)
            else None
        )
        uptime = 0.0
        if self._start_time:
            uptime = max(
                0.0,
                (datetime.now(timezone.utc) - self._start_time).total_seconds(),
            )
        return {
            "state": self._state,
            "running": self._state == "running",
            "last_error": last_error,
            "last_heartbeat": heartbeat,
            "uptime_secs": uptime,
            "restart_count": self._restart_count,
            "kill_switch": self._kill_switch.engaged_sync(),
        }

    async def start(self) -> None:
        async with self._async_lock:
            if self._state == "running" and self._supervisor_task and not self._supervisor_task.done():
                return
            self._stop_requested = False
            self._last_error = None
            self._last_error_stack = None
            self._start_time = datetime.now(timezone.utc)
            self.mark_tick()
            loop = asyncio.get_running_loop()
            self._supervisor_task = loop.create_task(self._run_supervisor())
            self._state = "running"
            log.info("orchestrator.start state=running")

    async def stop(self) -> None:
        async with self._async_lock:
            self._stop_requested = True
            task = self._supervisor_task
            self._supervisor_task = None
            if task:
                task.cancel()
            self._state = "stopped"
            log.info("orchestrator.stop requested")
        try:
            self._kill_switch.engage_sync()
        except Exception:  # pragma: no cover - defensive guard
            log.exception("orchestrator.stop kill-switch failed")
        if task:
            with suppress(asyncio.CancelledError):
                await task
        self.mark_tick()

    async def _run_supervisor(self) -> None:
        while not self._stop_requested:
            try:
                await self._run_worker_once()
                if self._stop_requested:
                    break
                log.warning("orchestrator.worker.exited unexpectedly; restarting")
                self._restart_count += 1
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # pragma: no cover - network/runtime failures
                self._last_error = str(exc)
                self._last_error_stack = traceback.format_exc()
                log.error("orchestrator.worker.crashed", exc_info=exc)
                if self._stop_requested:
                    break
                self._restart_count += 1
                await asyncio.sleep(2)
        self._state = "stopped"
        log.info("orchestrator.supervisor.stopped")

    async def _run_worker_once(self) -> None:
        self._kill_switch.reset_sync()
        self.mark_tick()
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        def _run() -> None:
            from services.runtime import runner as runtime_runner

            runtime_runner.main()

        try:
            await asyncio.to_thread(_run)
        finally:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task

    async def _heartbeat_loop(self) -> None:
        while True:
            self.mark_tick()
            await asyncio.sleep(1.0)

    def mark_tick(self) -> None:
        self._last_heartbeat = datetime.now(timezone.utc)


def get_orchestrator_status() -> Dict[str, Any]:
    supervisor = _CURRENT_SUPERVISOR
    snapshot: Dict[str, Any] = {}
    if supervisor is not None:
        try:
            snapshot = supervisor.status()
        except Exception:  # pragma: no cover - defensive snapshot guard
            snapshot = {}
    flags = runtime_flags_from_env()
    kill_switch_engaged = False
    if supervisor is not None:
        try:
            kill_switch_engaged = supervisor._kill_switch.engaged_sync()
        except Exception:  # pragma: no cover - defensive
            kill_switch_engaged = bool(snapshot.get("kill_switch"))
    uptime_secs = snapshot.get("uptime_secs")
    uptime_label: str | None = None
    if isinstance(uptime_secs, (int, float)):
        uptime_label = f"{uptime_secs:.2f}s"
    broker_impl = "MockBrokerAdapter" if getattr(flags, "mock_mode", False) else "AlpacaBrokerAdapter"
    return {
        "state": snapshot.get("state", "stopped"),
        "running": bool(snapshot.get("running")),
        "last_error": snapshot.get("last_error"),
        "last_heartbeat": snapshot.get("last_heartbeat"),
        "uptime": uptime_label,
        "restart_count": snapshot.get("restart_count"),
        "kill_switch": "Engaged" if kill_switch_engaged else "Standby",
        "kill_switch_engaged": kill_switch_engaged,
        "market_data_source": getattr(flags, "market_data_source", "mock"),
        "broker_impl": broker_impl,
        "profile": getattr(flags, "profile", "paper"),
        "dry_run": getattr(flags, "dry_run", False),
        "mock_mode": getattr(flags, "mock_mode", False),
    }


__all__ = [
    "OrchestratorSupervisor",
    "can_execute_trade",
    "get_last_order_attempt",
    "get_orchestrator_status",
    "record_order_attempt",
]
