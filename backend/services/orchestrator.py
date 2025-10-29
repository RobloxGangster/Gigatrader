from __future__ import annotations

import asyncio
import logging
import traceback
from collections import deque
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

from core.kill_switch import KillSwitch
from core.runtime_flags import get_runtime_flags


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


def can_execute_trade(
    flags, kill_switch_engaged: bool, *, kill_reason: str | None = None
) -> tuple[bool, str | None]:
    if kill_switch_engaged:
        return False, kill_reason or "kill_switch_engaged"
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
        self._kill_switch_events: Deque[Dict[str, Any]] = deque(maxlen=50)
        global _CURRENT_SUPERVISOR
        _CURRENT_SUPERVISOR = self

    def status(self) -> dict[str, Any]:
        """Return a thread-safe status snapshot."""

        flags = get_runtime_flags()
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
        kill_snapshot = self._kill_switch_snapshot()
        kill_engaged = bool(kill_snapshot.get("engaged"))
        kill_reason = kill_snapshot.get("reason")
        allowed, guard_reason = can_execute_trade(
            flags, kill_engaged, kill_reason=kill_reason
        )
        broker_impl = (
            "MockBrokerAdapter" if getattr(flags, "mock_mode", False) else "AlpacaBrokerAdapter"
        )
        uptime_label = f"{uptime:.2f}s"
        kill_label = "Engaged" if kill_engaged else "Standby"
        if kill_engaged and kill_reason:
            kill_label = f"Engaged ({kill_reason})"
        return {
            "state": self._state,
            "running": self._state == "running",
            "last_error": last_error,
            "last_heartbeat": heartbeat,
            "uptime_secs": uptime,
            "uptime": uptime_label,
            "restart_count": self._restart_count,
            "kill_switch": kill_label,
            "kill_switch_engaged": kill_engaged,
            "kill_switch_reason": kill_reason,
            "kill_switch_engaged_at": kill_snapshot.get("engaged_at"),
            "kill_switch_can_reset": (not kill_engaged)
            or not self._is_hard_violation(kill_reason),
            "kill_switch_history": self.kill_switch_history(),
            "can_trade": allowed,
            "trade_guard_reason": guard_reason,
            "market_data_source": getattr(flags, "market_data_source", "mock"),
            "broker_impl": broker_impl,
            "profile": getattr(flags, "profile", "paper"),
            "dry_run": getattr(flags, "dry_run", False),
            "mock_mode": getattr(flags, "mock_mode", False),
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
            self._kill_switch.engage_sync(reason="orchestrator_stopped")
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
        self.safe_arm_trading(requested_by="worker_boot")
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

    def kill_switch_history(self) -> List[Dict[str, Any]]:
        return list(self._kill_switch_events)

    def _record_kill_switch_event(
        self,
        action: str,
        *,
        reason: Optional[str] = None,
        requested_by: Optional[str] = None,
    ) -> None:
        event = {"ts": _iso_now(), "action": action}
        if reason:
            event["reason"] = reason
        if requested_by:
            event["requested_by"] = requested_by
        self._kill_switch_events.appendleft(event)

    @staticmethod
    def _is_hard_violation(reason: Optional[str]) -> bool:
        if not reason:
            return False
        return reason.startswith("risk:") or reason.startswith("breaker:")

    def _kill_switch_snapshot(self) -> Dict[str, Any]:
        try:
            info = self._kill_switch.info_sync()
        except Exception:  # pragma: no cover - defensive snapshot guard
            info = {"engaged": self._kill_switch.engaged_sync(), "reason": None, "engaged_at": None}
        if "engaged" not in info:
            info["engaged"] = self._kill_switch.engaged_sync()
        return info

    def reset_kill_switch(
        self,
        *,
        requested_by: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        snapshot = self._kill_switch_snapshot()
        engaged = bool(snapshot.get("engaged"))
        reason = snapshot.get("reason") if isinstance(snapshot.get("reason"), str) else None
        if not engaged:
            return snapshot
        if not force and self._is_hard_violation(reason):
            self._record_kill_switch_event("reset_blocked", reason=reason, requested_by=requested_by)
            return snapshot
        self._kill_switch.reset_sync()
        updated = self._kill_switch_snapshot()
        self._record_kill_switch_event("reset", reason=reason, requested_by=requested_by)
        return updated

    def safe_arm_trading(self, *, requested_by: str = "supervisor") -> Dict[str, Any]:
        return self.reset_kill_switch(requested_by=requested_by, force=False)


def get_orchestrator_status() -> Dict[str, Any]:
    supervisor = _CURRENT_SUPERVISOR
    if supervisor is not None:
        try:
            return supervisor.status()
        except Exception:  # pragma: no cover - defensive snapshot guard
            log.exception("orchestrator.status_snapshot_failed")
    flags = get_runtime_flags()
    kill_info = KillSwitch().info_sync()
    kill_engaged = bool(kill_info.get("engaged"))
    kill_reason = kill_info.get("reason") if isinstance(kill_info.get("reason"), str) else None
    allowed, guard_reason = can_execute_trade(
        flags, kill_engaged, kill_reason=kill_reason
    )
    broker_impl = (
        "MockBrokerAdapter" if getattr(flags, "mock_mode", False) else "AlpacaBrokerAdapter"
    )
    kill_label = "Engaged" if kill_engaged else "Standby"
    if kill_engaged and kill_reason:
        kill_label = f"Engaged ({kill_reason})"
    return {
        "state": "stopped",
        "running": False,
        "last_error": None,
        "last_heartbeat": None,
        "uptime_secs": 0.0,
        "uptime": "0.00s",
        "restart_count": 0,
        "kill_switch": kill_label,
        "kill_switch_engaged": kill_engaged,
        "kill_switch_reason": kill_reason,
        "kill_switch_engaged_at": kill_info.get("engaged_at"),
        "kill_switch_can_reset": (not kill_engaged)
        or not OrchestratorSupervisor._is_hard_violation(kill_info.get("reason")),
        "kill_switch_history": [],
        "can_trade": allowed,
        "trade_guard_reason": guard_reason,
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
