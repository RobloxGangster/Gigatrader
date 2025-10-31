"""Shared orchestrator status models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

PublicState = Literal["running", "stopped"]
TransitionState = Literal["starting", "stopping"]


class OrchestratorStatus(BaseModel):
    state: PublicState = "stopped"
    transition: TransitionState | None = None
    phase: Optional[str] = None
    running: bool = False
    last_error: Optional[str] = None
    thread_alive: bool = False
    restart_count: int = 0
    last_heartbeat: Optional[datetime] = None
    uptime_secs: float = 0.0
    last_error_stack: Optional[str] = None
    last_error_at: Optional[datetime] = None
    start_attempt_ts: Optional[datetime] = None
    last_shutdown_reason: Optional[str] = None
    kill_switch: Literal["Standby", "Engaged"] = "Standby"
    kill_switch_engaged: bool = False
    kill_switch_reason: Optional[str] = None
    kill_switch_engaged_at: Optional[datetime] = None
    kill_switch_can_reset: bool = True
    will_trade_at_open: bool = False
    preopen_queue_count: int = 0
    last_decision_at: Optional[datetime] = None


__all__ = [
    "OrchestratorStatus",
    "PublicState",
    "TransitionState",
]

