from __future__ import annotations

import asyncio
import logging
import traceback
from collections import deque
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

from backend.models.orchestrator import BrokerProfile, KillSwitchStatus, OrchestratorStatus
from core.kill_switch import KillSwitch
from core.market_hours import market_state
from core.runtime_flags import get_runtime_flags
from services.execution.preopen_queue import PreopenIntent, PreopenQueue


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

_decision_snapshot: Dict[str, Any] = {
    "will_trade_signal": False,
    "preopen_window_active": False,
    "will_trade_at_open": False,
    "preopen_queue_count": 0,
    "last_decision_at": None,
    "last_decision_iso": None,
    "last_signals": 0,
    "last_orders": 0,
}

_preopen_queue = PreopenQueue()
_preopen_queue_count: int = 0


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _iso_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


class OrchestratorStartupError(RuntimeError):
    """Raised when the orchestrator fails to transition into a running state."""


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


def record_decision_cycle(
    *,
    will_trade_at_open: bool,
    signals: int,
    orders: int,
    preopen_queue: int,
) -> None:
    ts = datetime.now(timezone.utc)
    iso_ts = ts.isoformat().replace("+00:00", "Z")
    _decision_snapshot.update(
        {
            "will_trade_signal": bool(will_trade_at_open),
            "last_decision_at": ts,
            "last_decision_iso": iso_ts,
            "last_signals": max(0, int(signals)),
            "last_orders": max(0, int(orders)),
        }
    )
    _sync_preopen_snapshot()
    log.info(
        "orchestrator.decision",
        extra={
            "will_trade_at_open": bool(will_trade_at_open),
            "signals": int(signals),
            "orders": int(orders),
            "preopen_queue": max(0, int(preopen_queue)),
        },
    )


def _decision_state_snapshot() -> Dict[str, Any]:
    payload = dict(_decision_snapshot)
    return payload


def _sync_preopen_snapshot() -> None:
    queue_count = max(0, int(_preopen_queue_count))
    signal = bool(_decision_snapshot.get("will_trade_signal"))
    window_active = bool(_decision_snapshot.get("preopen_window_active"))
    _decision_snapshot["preopen_queue_count"] = queue_count
    _decision_snapshot["will_trade_at_open"] = bool(queue_count) or (signal and window_active)


def _set_preopen_queue_count(count: int) -> None:
    global _preopen_queue_count
    _preopen_queue_count = max(0, int(count))
    _sync_preopen_snapshot()


async def queue_preopen_intent(intent: PreopenIntent) -> None:
    await _preopen_queue.enqueue(intent)
    count = await _preopen_queue.count()
    _set_preopen_queue_count(count)


async def drain_preopen_queue() -> List[PreopenIntent]:
    intents = await _preopen_queue.drain()
    _set_preopen_queue_count(0)
    return intents


async def refresh_preopen_queue_count() -> int:
    count = await _preopen_queue.count()
    _set_preopen_queue_count(count)
    return count


def get_preopen_queue_count() -> int:
    return max(0, int(_preopen_queue_count))


def set_preopen_window_active(active: bool) -> None:
    _decision_snapshot["preopen_window_active"] = bool(active)
    _sync_preopen_snapshot()


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
    """Supervise the trading runtime and expose health/kill-switch state."""

    def __init__(self, kill_switch: KillSwitch) -> None:
        self._kill_switch = kill_switch
        self._state: str = "stopped"
        self._internal_state: str = "stopped"
        self._async_lock = asyncio.Lock()
        self._supervisor_task: asyncio.Task[None] | None = None
        self._stop_requested = False
        self._last_error: str | None = None
        self._last_error_stack: str | None = None
        self._last_error_at: datetime | None = None
        self._last_heartbeat: datetime | None = None
        self._start_time: datetime | None = None
        self._start_attempt_ts: datetime | None = None
        self._last_shutdown_reason: str | None = None
        self._trade_guard_reason: str | None = None
        self._restart_count = 0
        self._runtime_started = False
        self._kill_switch_events: Deque[Dict[str, Any]] = deque(maxlen=50)
        global _CURRENT_SUPERVISOR
        _CURRENT_SUPERVISOR = self

    def status(self) -> OrchestratorStatus:
        """Return a thread-safe status snapshot."""

        flags = get_runtime_flags()
        heartbeat = _iso_dt(self._last_heartbeat)
        uptime = 0.0
        if self._start_time:
            uptime = max(
                0.0,
                (datetime.now(timezone.utc) - self._start_time).total_seconds(),
            )
        kill_snapshot = self._kill_switch_snapshot()
        kill_engaged = bool(kill_snapshot.get("engaged"))
        kill_reason = (
            kill_snapshot.get("reason") if isinstance(kill_snapshot.get("reason"), str) else None
        )
        kill_status = KillSwitchStatus(
            engaged=kill_engaged,
            reason=kill_reason,
            can_reset=(not kill_engaged) or not self._is_hard_violation(kill_reason),
        )
        allowed_by_policy, base_guard_reason = can_execute_trade(
            flags, kill_engaged, kill_reason=kill_reason
        )
        trade_guard_reason = self._trade_guard_reason or base_guard_reason
        can_trade = bool(allowed_by_policy) and self._trade_guard_reason is None
        broker_impl = (
            "MockBrokerAdapter" if getattr(flags, "mock_mode", False) else "AlpacaBrokerAdapter"
        )

        manager_state: str | None = None
        manager_thread_alive = False
        manager_snapshot: dict[str, Any] | None = None
        try:  # Deferred import to avoid circular dependency during app startup
            from backend.services.orchestrator_manager import orchestrator_manager

            manager_snapshot = orchestrator_manager.get_status()
            if isinstance(manager_snapshot, dict):
                manager_state = str(manager_snapshot.get("state") or "") or None
                manager_thread_alive = bool(manager_snapshot.get("thread_alive"))
        except Exception:  # pragma: no cover - defensive guard
            manager_snapshot = None

        thread_alive = self._runtime_started or manager_thread_alive

        decision_state = _decision_state_snapshot()
        queue_count = get_preopen_queue_count()
        will_trade_flag = bool(decision_state.get("will_trade_at_open"))
        last_decision_iso = decision_state.get("last_decision_iso")
        last_decision_at = decision_state.get("last_decision_at")
        if last_decision_iso:
            last_decision_value = last_decision_iso
        else:
            last_decision_value = _iso_dt(last_decision_at)

        public_state = "running" if self._internal_state == "running" else "stopped"
        transition = (
            self._internal_state if self._internal_state in {"starting", "stopping"} else None
        )

        broker_profile = BrokerProfile(
            broker=str(getattr(flags, "broker", "alpaca")),
            profile=str(getattr(flags, "profile", "paper")),
            mode=getattr(flags, "broker_mode", "paper"),
        )

        status = OrchestratorStatus(
            state=public_state,
            transition=transition,
            kill_switch=kill_status,
            phase=self._state,
            running=public_state == "running",
            thread_alive=thread_alive,
            start_attempt_ts=_iso_dt(self._start_attempt_ts),
            last_shutdown_reason=self._last_shutdown_reason,
            will_trade_at_open=will_trade_flag,
            preopen_queue_count=queue_count,
            broker=broker_profile,
            last_error=self._last_error,
            last_error_at=_iso_dt(self._last_error_at),
            last_error_stack=self._last_error_stack,
            last_heartbeat=heartbeat,
            uptime_secs=uptime,
            uptime_label=f"{uptime:.2f}s",
            uptime=f"{uptime:.2f}s",
            restart_count=self._restart_count,
            can_trade=can_trade,
            trade_guard_reason=trade_guard_reason,
            market_data_source=getattr(flags, "market_data_source", "mock"),
            market_state=market_state(),
            mock_mode=bool(getattr(flags, "mock_mode", False)),
            dry_run=bool(getattr(flags, "dry_run", False)),
            profile=str(getattr(flags, "profile", "paper")),
            broker_impl=broker_impl,
            manager=manager_snapshot,
            kill_switch_history=self.kill_switch_history(),
            last_decision_at=last_decision_value,
            last_decision_ts=last_decision_iso,
            last_decision_signals=int(decision_state.get("last_signals") or 0),
            last_decision_orders=int(decision_state.get("last_orders") or 0),
            kill_switch_engaged=kill_engaged,
            kill_switch_reason=kill_reason,
            kill_switch_engaged_at=kill_snapshot.get("engaged_at"),
            kill_switch_can_reset=kill_status.can_reset,
        )
        return status

    async def start(self) -> None:
        async with self._async_lock:
            if (
                self._supervisor_task
                and not self._supervisor_task.done()
                and self._state in {"starting", "running"}
            ):
                return
            self._stop_requested = False
            self._last_error = None
            self._last_error_stack = None
            self._last_error_at = None
            self._last_shutdown_reason = None
            self._trade_guard_reason = None
            self._start_time = None
            self._start_attempt_ts = datetime.now(timezone.utc)
            self._runtime_started = False
            self._restart_count = 0
            loop = asyncio.get_running_loop()
            self._supervisor_task = loop.create_task(self._run_supervisor())
            self._state = "starting"
            self._internal_state = "starting"
            log.info(
                "orchestrator.start requested",
                extra={"start_attempt": _iso_dt(self._start_attempt_ts)},
            )
        self.mark_tick()

    async def stop(self) -> None:
        async with self._async_lock:
            task = self._supervisor_task
            self._supervisor_task = None
            if task:
                task.cancel()
            self._stop_requested = True
            self._state = "stopping"
            self._internal_state = "stopping"
            self._last_shutdown_reason = "requested_stop"
            log.info("orchestrator.stop requested")
        if task:
            with suppress(asyncio.CancelledError):
                await task
        async with self._async_lock:
            self._state = "stopped"
            self._internal_state = "stopped"
            self._stop_requested = False
            self._runtime_started = False
            self._trade_guard_reason = None
            self._start_time = None
        self.mark_tick()

    async def _run_supervisor(self) -> None:
        log.info("orchestrator.supervisor.loop.start")
        try:
            while not self._stop_requested:
                try:
                    await self._run_worker_once()
                except asyncio.CancelledError:
                    raise
                except OrchestratorStartupError as exc:
                    self._handle_start_failure(str(exc))
                    break
                except Exception as exc:  # pragma: no cover - runtime/IO failures
                    self._handle_worker_exception(exc)
                    break

                if self._stop_requested:
                    break

                self._handle_unexpected_exit()
                break
        except asyncio.CancelledError:
            pass
        finally:
            if self._state not in {"crashed", "error_startup"}:
                if self._stop_requested and self._state != "stopped":
                    self._state = "stopped"
                    self._internal_state = "stopped"
                elif not self._stop_requested and self._state not in {"stopped", "stopping"}:
                    self._state = "stopped"
                    self._internal_state = "stopped"
            if self._internal_state not in {"starting", "running", "stopping", "stopped"}:
                self._internal_state = "stopped"
            self.mark_tick()
            log.info("orchestrator.supervisor.stopped", extra={"state": self._state})

    async def _run_worker_once(self) -> None:
        arm_snapshot = self.safe_arm_trading(requested_by="worker_boot")
        if bool(arm_snapshot.get("engaged")):
            reason = (
                arm_snapshot.get("reason")
                if isinstance(arm_snapshot.get("reason"), str)
                else "kill_switch_engaged"
            )
            raise OrchestratorStartupError(f"kill_switch_engaged:{reason}")
        self._state = "running"
        self._internal_state = "running"
        self._trade_guard_reason = None
        if self._start_time is None:
            self._start_time = datetime.now(timezone.utc)
        self.mark_tick()
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        def _run() -> None:
            from services.runtime import runner as runtime_runner

            self._runtime_started = True
            runtime_runner.main()

        try:
            await asyncio.to_thread(_run)
        finally:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
            self._runtime_started = False
            self._internal_state = "stopped" if self._stop_requested else self._internal_state
            self.mark_tick()

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
        auto_request = requested_by in {None, "supervisor", "worker_boot"}
        if not force:
            if self._is_hard_violation(reason):
                self._record_kill_switch_event(
                    "reset_blocked", reason=reason, requested_by=requested_by
                )
                return snapshot
            if auto_request and reason == "orchestrator_crashed":
                self._record_kill_switch_event(
                    "reset_blocked", reason=reason, requested_by=requested_by
                )
                return snapshot
        self._kill_switch.reset_sync()
        updated = self._kill_switch_snapshot()
        self._record_kill_switch_event("reset", reason=reason, requested_by=requested_by)
        if not bool(updated.get("engaged")):
            self._trade_guard_reason = None
        return updated

    def safe_arm_trading(self, *, requested_by: str = "supervisor") -> Dict[str, Any]:
        snapshot = self.reset_kill_switch(requested_by=requested_by, force=False)
        if bool(snapshot.get("engaged")):
            reason = snapshot.get("reason") if isinstance(snapshot.get("reason"), str) else None
            if reason == "orchestrator_crashed":
                self._trade_guard_reason = "orchestrator_crashed"
        return snapshot

    def _engage_kill_switch(self, reason: str, *, requested_by: str) -> None:
        try:
            self._kill_switch.engage_sync(reason=reason)
        except Exception:  # pragma: no cover - defensive guard
            log.exception("orchestrator.kill_switch.engage_failed", extra={"reason": reason})
        else:
            self._record_kill_switch_event("engaged", reason=reason, requested_by=requested_by)

    def _handle_worker_exception(self, exc: Exception) -> None:
        self._last_error = str(exc)
        self._last_error_stack = traceback.format_exc()
        self._last_error_at = datetime.now(timezone.utc)
        if self._runtime_started:
            self._state = "crashed"
            self._internal_state = "stopped"
            self._trade_guard_reason = "orchestrator_crashed"
            self._last_shutdown_reason = "crashed"
            self._restart_count += 1
            log.error("orchestrator.worker.crashed", exc_info=exc)
            self._engage_kill_switch("orchestrator_crashed", requested_by="supervisor")
        else:
            self._state = "error_startup"
            self._internal_state = "stopped"
            self._trade_guard_reason = "startup_failed"
            self._last_shutdown_reason = "startup_failed"
            log.error("orchestrator.worker.startup_failed", exc_info=exc)
        self._stop_requested = True

    def _handle_start_failure(self, message: str) -> None:
        self._last_error = message
        self._last_error_stack = None
        self._last_error_at = datetime.now(timezone.utc)
        guard_reason = self._trade_guard_reason or (
            "orchestrator_crashed" if "orchestrator_crashed" in str(message).lower() else "startup_failed"
        )
        if guard_reason == "orchestrator_crashed":
            self._state = "crashed"
            self._last_shutdown_reason = "crashed"
            self._restart_count += 1
        else:
            self._state = "error_startup"
            self._last_shutdown_reason = "startup_failed"
        self._internal_state = "stopped"
        self._trade_guard_reason = guard_reason
        log.error("orchestrator.worker.startup_blocked", extra={"reason": message})
        self._stop_requested = True

    def _handle_unexpected_exit(self) -> None:
        self._last_error = "orchestrator worker exited unexpectedly"
        self._last_error_stack = None
        self._last_error_at = datetime.now(timezone.utc)
        self._state = "crashed"
        self._internal_state = "stopped"
        self._trade_guard_reason = "orchestrator_crashed"
        self._last_shutdown_reason = "crashed"
        self._restart_count += 1
        log.error("orchestrator.worker.exited_unexpectedly")
        self._engage_kill_switch("orchestrator_crashed", requested_by="supervisor")
        self._stop_requested = True


def get_orchestrator_status() -> OrchestratorStatus:
    supervisor = _CURRENT_SUPERVISOR
    if supervisor is not None:
        try:
            snapshot = supervisor.status()
            if isinstance(snapshot, OrchestratorStatus):
                return snapshot
            return OrchestratorStatus(**snapshot)
        except Exception:  # pragma: no cover - defensive snapshot guard
            log.exception("orchestrator.status_snapshot_failed")
    flags = get_runtime_flags()
    kill_info = KillSwitch().info_sync()
    kill_engaged = bool(kill_info.get("engaged"))
    kill_reason = kill_info.get("reason") if isinstance(kill_info.get("reason"), str) else None
    kill_status = KillSwitchStatus(
        engaged=kill_engaged,
        reason=kill_reason,
        can_reset=(not kill_engaged)
        or not OrchestratorSupervisor._is_hard_violation(kill_info.get("reason")),
    )
    allowed, guard_reason = can_execute_trade(
        flags, kill_engaged, kill_reason=kill_reason
    )
    broker_impl = (
        "MockBrokerAdapter" if getattr(flags, "mock_mode", False) else "AlpacaBrokerAdapter"
    )
    decision_state = _decision_state_snapshot()
    queue_count = get_preopen_queue_count()
    will_trade_flag = bool(decision_state.get("will_trade_at_open"))
    last_decision_iso = decision_state.get("last_decision_iso")
    if last_decision_iso:
        last_decision_value = last_decision_iso
    else:
        last_decision_value = _iso_dt(decision_state.get("last_decision_at"))

    broker_profile = BrokerProfile(
        broker=str(getattr(flags, "broker", "alpaca")),
        profile=str(getattr(flags, "profile", "paper")),
        mode=getattr(flags, "broker_mode", "paper"),
    )

    return OrchestratorStatus(
        state="stopped",
        transition=None,
        kill_switch=kill_status,
        phase="stopped",
        running=False,
        thread_alive=False,
        start_attempt_ts=None,
        last_shutdown_reason=None,
        will_trade_at_open=will_trade_flag,
        preopen_queue_count=queue_count,
        broker=broker_profile,
        last_error=None,
        last_error_at=None,
        last_error_stack=None,
        last_heartbeat=None,
        uptime_secs=0.0,
        uptime_label="0.00s",
        uptime="0.00s",
        restart_count=0,
        can_trade=allowed,
        trade_guard_reason=guard_reason,
        market_data_source=getattr(flags, "market_data_source", "mock"),
        market_state=market_state(),
        mock_mode=bool(getattr(flags, "mock_mode", False)),
        dry_run=bool(getattr(flags, "dry_run", False)),
        profile=str(getattr(flags, "profile", "paper")),
        broker_impl=broker_impl,
        manager=None,
        kill_switch_history=[],
        last_decision_at=last_decision_value,
        last_decision_ts=last_decision_iso,
        last_decision_signals=int(decision_state.get("last_signals") or 0),
        last_decision_orders=int(decision_state.get("last_orders") or 0),
        kill_switch_engaged=kill_engaged,
        kill_switch_reason=kill_reason,
        kill_switch_engaged_at=kill_info.get("engaged_at"),
        kill_switch_can_reset=kill_status.can_reset,
    )


__all__ = [
    "OrchestratorSupervisor",
    "can_execute_trade",
    "drain_preopen_queue",
    "get_preopen_queue_count",
    "record_decision_cycle",
    "get_last_order_attempt",
    "get_orchestrator_status",
    "queue_preopen_intent",
    "record_order_attempt",
    "refresh_preopen_queue_count",
    "set_preopen_window_active",
]
