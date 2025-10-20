"""Dependency accessors shared by Control Center routers."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.execution.alpaca_adapter import AlpacaAdapter, AlpacaUnauthorized
from app.market.stream_manager import StreamManager
from core.broker_config import is_mock
from core.kill_switch import KillSwitch

from backend.services import reconcile


class BrokerService:
    """Thin wrapper exposing broker helpers expected by the routers."""

    def __init__(self) -> None:
        self._adapter = AlpacaAdapter()

    def get_account(self) -> Dict[str, Any]:
        return self._adapter.fetch_account()

    def get_positions(self) -> List[Dict[str, Any]]:
        return self._adapter.fetch_positions()

    def get_orders(self, *, status: str = "all", limit: int = 50) -> List[Dict[str, Any]]:
        orders = self._adapter.fetch_orders()
        scope = status.lower()
        if scope not in {"all", "open", "closed"}:
            raise ValueError(f"unsupported status scope: {status}")

        if scope == "all":
            filtered = orders
        else:
            open_statuses = {
                "new",
                "accepted",
                "pending_new",
                "partially_filled",
                "open",
            }
            closed_statuses = {
                "filled",
                "canceled",
                "rejected",
                "expired",
                "done_for_day",
                "stopped",
                "suspended",
                "calculated",
                "replaced",
            }
            wanted = open_statuses if scope == "open" else closed_statuses
            filtered = [
                order
                for order in orders
                if str(order.get("status", "")).lower() in wanted
            ]
        return filtered[:limit]


@dataclass
class StrategyConfigState:
    preset: str = "balanced"
    enabled: bool = True
    strategies: Dict[str, bool] = field(
        default_factory=lambda: {
            "intraday_momo": True,
            "intraday_revert": True,
            "swing_breakout": False,
        }
    )
    confidence_threshold: float = 0.55
    expected_value_threshold: float = 0.0
    universe: List[str] = field(default_factory=lambda: ["AAPL", "MSFT", "NVDA", "SPY"])
    cooldown_sec: int = 30
    pacing_per_minute: int = 12
    dry_run: bool = False


class StrategyRegistryService:
    """In-memory strategy registry mirroring the legacy API behaviour."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._config = StrategyConfigState()

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            payload = asdict(self._config)
        payload.setdefault("preset", self._config.preset)
        payload["mock_mode"] = is_mock()
        return payload

    def apply_patch(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        if not patch:
            return self.snapshot()

        with self._lock:
            current = asdict(self._config)
            strategies = dict(current.get("strategies", {}))

            incoming_strategies = patch.get("strategies")
            if isinstance(incoming_strategies, dict):
                strategies.update({k: bool(v) for k, v in incoming_strategies.items()})

            enable_patch = patch.get("enable")
            if isinstance(enable_patch, dict):
                strategies.update({k: bool(v) for k, v in enable_patch.items()})

            if strategies:
                current["strategies"] = strategies

            for key in (
                "preset",
                "enabled",
                "confidence_threshold",
                "expected_value_threshold",
                "universe",
                "cooldown_sec",
                "pacing_per_minute",
                "dry_run",
            ):
                if key in patch:
                    current[key] = patch[key]

            if "pacing_sec" in patch:
                try:
                    pace = float(patch["pacing_sec"])
                    if pace > 0:
                        current["pacing_per_minute"] = max(1, int(60 / pace))
                except Exception:
                    pass

            self._config = StrategyConfigState(**current)

        _mark_orchestrator_tick()
        return self.snapshot()


@dataclass
class RiskConfigState:
    daily_loss_limit: float = 2000.0
    max_positions: int = 10
    per_symbol_notional: float = 20000.0
    portfolio_notional: float = 100000.0
    bracket_enabled: bool = True
    cooldown_sec: int = 0


class RiskConfigService:
    """Mutable risk configuration exposed via the REST API."""

    def __init__(self, kill_switch: KillSwitch) -> None:
        self._lock = threading.Lock()
        self._config = RiskConfigState()
        self._kill_switch = kill_switch

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            payload = asdict(self._config)
        payload["kill_switch"] = self._kill_switch.engaged_sync()
        payload["mock_mode"] = is_mock()
        return payload

    def apply_patch(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        if not patch:
            return self.snapshot()

        with self._lock:
            current = asdict(self._config)
            for key in current:
                if key in patch:
                    current[key] = patch[key]
            self._config = RiskConfigState(**current)
        return self.snapshot()

    def engage_kill_switch(self) -> None:
        self._kill_switch.engage_sync()

    def reset_kill_switch(self) -> None:
        self._kill_switch.reset_sync()


class MetricsService:
    """Expose P&L and exposure summaries used by the Control Center."""

    def pnl_summary(self) -> Dict[str, float]:
        if is_mock():
            return {
                "realized_today": 0.0,
                "unrealized": 0.0,
                "total": 0.0,
                "day_pl_pct": 0.0,
            }
        acct = reconcile.pull_account()
        realized = float(acct.get("daytrade_pl") or acct.get("day_pl") or 0.0)
        unrealized = float(
            acct.get("unrealized_pl")
            or acct.get("unrealized_intraday_pl")
            or 0.0
        )
        equity = float(acct.get("equity") or 0.0)
        last_equity = float(acct.get("last_equity") or (equity or 1.0))
        day_pl_pct = 0.0
        if last_equity:
            day_pl_pct = (equity - last_equity) / float(last_equity)
        return {
            "realized_today": realized,
            "unrealized": unrealized,
            "total": realized + unrealized,
            "day_pl_pct": day_pl_pct,
        }

    def exposure(self) -> Dict[str, float]:
        if is_mock():
            return {"gross": 0.0, "net": 0.0, "long_exposure": 0.0, "short_exposure": 0.0}
        positions = reconcile.pull_positions()
        long_exposure = 0.0
        short_exposure = 0.0
        for pos in positions:
            market_value = float(pos.get("market_value") or 0.0)
            if market_value >= 0:
                long_exposure += market_value
            else:
                short_exposure += market_value
        gross = long_exposure + abs(short_exposure)
        net = long_exposure + short_exposure
        return {
            "gross": gross,
            "net": net,
            "long_exposure": long_exposure,
            "short_exposure": short_exposure,
        }


class OrchestratorService:
    """Keep track of trading runner status for the REST API."""

    def __init__(self, kill_switch: KillSwitch) -> None:
        self._kill_switch = kill_switch
        self._lock = threading.Lock()
        self._runner_thread: Optional[threading.Thread] = None
        self._running = False
        self._profile = "paper"
        self._last_run_id: Optional[str] = None
        self._meta: Dict[str, Any] = {
            "last_error": None,
            "last_tick_ts": None,
            "routed_orders_24h": 0,
        }

    def _format_ts(self, ts: Optional[float]) -> Optional[str]:
        if not ts:
            return None
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    def mark_tick(self) -> None:
        with self._lock:
            self._meta["last_tick_ts"] = time.time()

    def _run_runner(self) -> None:
        try:
            from services.runtime import runner as runtime_runner

            runtime_runner.main()
        except Exception as exc:  # noqa: BLE001 - propagate as status
            with self._lock:
                self._meta["last_error"] = str(exc)
        finally:
            with self._lock:
                self._running = False
                self._runner_thread = None
                self._meta["last_tick_ts"] = time.time()

    def start_sync(self, *, mode: str = "paper", preset: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            if self._running:
                return {"run_id": self._last_run_id or "active"}

            if mode == "paper":
                os.environ["TRADING_MODE"] = "paper"
                os.environ["ALPACA_PAPER"] = "true"
            else:
                os.environ["TRADING_MODE"] = "live"
                os.environ["ALPACA_PAPER"] = "false"

            if preset:
                os.environ["RISK_PROFILE"] = preset

            self._profile = mode
            self._running = True
            self._meta["last_error"] = None
            self._last_run_id = f"{mode}-{int(time.time())}"
            self._meta["last_tick_ts"] = time.time()
            thread = threading.Thread(target=self._run_runner, daemon=True)
            self._runner_thread = thread
            thread.start()
            return {"run_id": self._last_run_id}

    def stop_sync(self) -> Dict[str, Any]:
        with self._lock:
            self._running = False
            self._meta["last_tick_ts"] = time.time()
        try:
            self._kill_switch.engage_sync()
        except Exception:
            pass
        return {"ok": True}

    def set_last_error(self, message: Optional[str]) -> None:
        with self._lock:
            self._meta["last_error"] = message

    def status(self) -> Dict[str, Any]:
        with self._lock:
            snapshot = {
                "running": self._running,
                "profile": self._profile,
                "last_error": self._meta.get("last_error"),
                "last_tick_ts": self._format_ts(self._meta.get("last_tick_ts")),
                "routed_orders_24h": int(self._meta.get("routed_orders_24h") or 0),
                "kill_switch": self._kill_switch.engaged_sync(),
                "last_run_id": self._last_run_id,
            }
        return snapshot


_broker: Optional[BrokerService] = None
_stream: Optional[StreamManager] = None
_strategy: Optional[StrategyRegistryService] = None
_risk: Optional[RiskConfigService] = None
_orchestrator: Optional[OrchestratorService] = None
_metrics: Optional[MetricsService] = None
_kill_switch = KillSwitch()


def _mark_orchestrator_tick() -> None:
    orch = get_orchestrator()
    orch.mark_tick()


def get_kill_switch() -> KillSwitch:
    return _kill_switch


def get_broker() -> BrokerService:
    global _broker
    if _broker is None:
        _broker = BrokerService()
    return _broker


def get_stream_manager() -> StreamManager:
    global _stream
    if _stream is None:
        _stream = StreamManager()
    return _stream


def get_strategy_registry() -> StrategyRegistryService:
    global _strategy
    if _strategy is None:
        _strategy = StrategyRegistryService()
    return _strategy


def get_risk_manager() -> RiskConfigService:
    global _risk
    if _risk is None:
        _risk = RiskConfigService(_kill_switch)
    return _risk


def get_orchestrator() -> OrchestratorService:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = OrchestratorService(_kill_switch)
    return _orchestrator


def get_metrics() -> MetricsService:
    global _metrics
    if _metrics is None:
        _metrics = MetricsService()
    return _metrics
