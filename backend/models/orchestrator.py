from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, validator


class BrokerProfile(BaseModel):
    broker: str = "alpaca"
    profile: str = "paper"
    mode: str = "live"


class KillSwitchStatus(BaseModel):
    engaged: bool
    reason: Optional[str] = None
    can_reset: bool = True


class OrchestratorStatus(BaseModel):
    model_config = ConfigDict(extra="allow")

    state: str = Field(..., description="running|stopped")
    transition: Optional[str] = Field(None, description="starting|stopping|null")
    kill_switch: KillSwitchStatus
    phase: Optional[str] = None
    running: bool = False
    thread_alive: bool = False
    start_attempt_ts: Optional[str] = None
    last_shutdown_reason: Optional[str] = None
    will_trade_at_open: bool = False
    preopen_queue_count: int = 0
    broker: BrokerProfile
    ok: bool = True
    last_error: Optional[str] = None
    last_error_at: Optional[str] = None
    last_error_stack: Optional[str] = None
    last_heartbeat: Optional[str] = None
    uptime_secs: float = 0.0
    uptime_label: Optional[str] = None
    uptime: Optional[str] = None
    restart_count: int = 0
    can_trade: bool = False
    trade_guard_reason: Optional[str] = None
    market_data_source: Optional[str] = None
    market_state: Optional[str] = None
    mock_mode: bool = False
    dry_run: bool = False
    profile: Optional[str] = None
    broker_impl: Optional[str] = None
    manager: Optional[dict[str, Any]] = None
    kill_switch_history: list[dict[str, Any]] = Field(default_factory=list)
    last_decision_at: Optional[str] = None
    last_decision_ts: Optional[str] = None
    last_decision_signals: int = 0
    last_decision_orders: int = 0
    kill_switch_engaged: bool = False
    kill_switch_reason: Optional[str] = None
    kill_switch_engaged_at: Optional[str] = None
    kill_switch_can_reset: bool = True

    @validator("state")
    def _state_ok(cls, value: str) -> str:
        if value not in {"running", "stopped"}:
            raise ValueError("state must be running or stopped")
        return value

    @validator("transition")
    def _transition_ok(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if value not in {"starting", "stopping"}:
            raise ValueError("transition must be starting|stopping or null")
        return value


__all__ = ["BrokerProfile", "KillSwitchStatus", "OrchestratorStatus"]

