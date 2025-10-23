"""Dependency accessors shared by Control Center routers."""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from app.execution.alpaca_adapter import AlpacaUnauthorized
from core.broker_config import is_mock
from core.kill_switch import KillSwitch
from core.runtime_flags import get_runtime_flags

from backend.services import reconcile
from backend.services.broker_factory import make_broker_adapter
from backend.services.orchestrator import OrchestratorSupervisor
from backend.services.stream_factory import StreamService, make_stream_service


logger = logging.getLogger(__name__)

try:
    from app.orchestrator.config import (
        try_load_orchestrator_config as _try_load_orchestrator_config,
        try_load_risk_config as _try_load_risk_config,
        try_load_strategy_config as _try_load_strategy_config,
    )
except RuntimeError as exc:  # pragma: no cover - import guard
    YAML_IMPORT_ERROR = str(exc)

    def try_load_orchestrator_config() -> Dict[str, Any]:
        raise RuntimeError(YAML_IMPORT_ERROR)

    def try_load_strategy_config() -> Dict[str, Any]:
        raise RuntimeError(YAML_IMPORT_ERROR)

    def try_load_risk_config() -> Dict[str, Any]:
        raise RuntimeError(YAML_IMPORT_ERROR)

    logger.error("%s", YAML_IMPORT_ERROR)
else:  # pragma: no cover - executed in production
    YAML_IMPORT_ERROR = None
    try_load_orchestrator_config = _try_load_orchestrator_config
    try_load_strategy_config = _try_load_strategy_config
    try_load_risk_config = _try_load_risk_config


class BrokerService:
    """Thin wrapper exposing broker helpers expected by the routers."""

    def __init__(self) -> None:
        self._flags = get_runtime_flags()
        self._adapter = make_broker_adapter(self._flags)

    @property
    def adapter(self):
        return self._adapter

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

    def last_headers(self) -> Mapping[str, str] | None:
        last_headers = getattr(self._adapter, "last_headers", None)
        if last_headers is None:
            return None
        if isinstance(last_headers, Mapping):
            return dict(last_headers)
        return None


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

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "StrategyConfigState":
        if not data:
            return cls()
        base = cls()
        payload = asdict(base)

        if "preset" in data and isinstance(data["preset"], str):
            payload["preset"] = data["preset"]
        if "enabled" in data:
            payload["enabled"] = bool(data["enabled"])

        strategies = data.get("strategies")
        if isinstance(strategies, Mapping):
            payload["strategies"] = {str(k): bool(v) for k, v in strategies.items()}

        if "confidence_threshold" in data:
            try:
                payload["confidence_threshold"] = float(data["confidence_threshold"])
            except Exception:
                pass
        if "expected_value_threshold" in data:
            try:
                payload["expected_value_threshold"] = float(data["expected_value_threshold"])
            except Exception:
                pass

        universe = data.get("universe")
        if isinstance(universe, str):
            payload["universe"] = [sym.strip().upper() for sym in universe.split(",") if sym.strip()]
        elif isinstance(universe, Mapping):
            payload["universe"] = [str(sym).upper() for sym in universe.values() if str(sym).strip()]
        elif isinstance(universe, (list, tuple, set)):
            payload["universe"] = [str(sym).upper() for sym in universe if str(sym).strip()]

        if "cooldown_sec" in data:
            try:
                payload["cooldown_sec"] = int(float(data["cooldown_sec"]))
            except Exception:
                pass
        if "pacing_per_minute" in data:
            try:
                payload["pacing_per_minute"] = int(float(data["pacing_per_minute"]))
            except Exception:
                pass
        if "dry_run" in data:
            payload["dry_run"] = bool(data["dry_run"])

        return cls(**payload)


class StrategyRegistryService:
    """In-memory strategy registry mirroring the legacy API behaviour."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._warnings: List[str] = []
        if YAML_IMPORT_ERROR:
            self._warnings.append(YAML_IMPORT_ERROR)
        config_payload: Dict[str, Any] = {}
        try:
            config_payload = try_load_strategy_config()
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.exception("Strategy config load failed: %s", exc)
            self._warnings.append(f"Strategy config unavailable: {exc}")
            config_payload = {}
        self._config = StrategyConfigState.from_mapping(config_payload)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            payload = asdict(self._config)
        payload.setdefault("preset", self._config.preset)
        payload["mock_mode"] = is_mock()
        if self._warnings:
            payload["warnings"] = list(self._warnings)
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

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "RiskConfigState":
        if not data:
            return cls()
        base = cls()
        payload = asdict(base)

        def _assign(key: str, caster) -> None:
            if key not in data:
                return
            try:
                payload[key] = caster(data[key])
            except Exception:
                pass

        _assign("daily_loss_limit", float)
        _assign("max_positions", lambda v: int(float(v)))
        _assign("per_symbol_notional", float)
        _assign("portfolio_notional", float)
        _assign("bracket_enabled", bool)
        _assign("cooldown_sec", lambda v: int(float(v)))

        return cls(**payload)


class RiskConfigService:
    """Mutable risk configuration exposed via the REST API."""

    def __init__(self, kill_switch: KillSwitch) -> None:
        self._lock = threading.Lock()
        self._kill_switch = kill_switch
        self._warnings: List[str] = []
        if YAML_IMPORT_ERROR:
            self._warnings.append(YAML_IMPORT_ERROR)
        config_payload: Dict[str, Any] = {}
        try:
            config_payload = try_load_risk_config()
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.exception("Risk config load failed: %s", exc)
            self._warnings.append(f"Risk config unavailable: {exc}")
            config_payload = {}
        self._config = RiskConfigState.from_mapping(config_payload)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            payload = asdict(self._config)
        payload["kill_switch"] = self._kill_switch.engaged_sync()
        payload["mock_mode"] = is_mock()
        if self._warnings:
            payload["warnings"] = list(self._warnings)
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
                "day_pl": 0.0,
                "realized": 0.0,
                "unrealized": 0.0,
                "cumulative": 0.0,
            }
        acct = reconcile.pull_account()
        realized = float(acct.get("daytrade_pl") or acct.get("day_pl") or 0.0)
        unrealized = float(
            acct.get("unrealized_pl")
            or acct.get("unrealized_intraday_pl")
            or 0.0
        )
        equity = float(acct.get("equity") or 0.0)
        last_equity = float(acct.get("last_equity") or equity)
        day_pl = realized + unrealized
        cumulative = float(acct.get("cumulative_pl") or (equity - last_equity + day_pl))
        return {
            "day_pl": day_pl,
            "realized": realized,
            "unrealized": unrealized,
            "cumulative": cumulative,
        }

    def exposure(self) -> Dict[str, Any]:
        if is_mock():
            return {"net": 0.0, "gross": 0.0, "by_symbol": []}
        try:
            positions = reconcile.pull_positions()
        except Exception:
            return {"net": 0.0, "gross": 0.0, "by_symbol": []}
        by_symbol: List[Dict[str, Any]] = []
        net = 0.0
        gross = 0.0
        for pos in positions:
            symbol = pos.get("symbol") or pos.get("asset_symbol") or "?"
            market_value = float(pos.get("market_value") or 0.0)
            by_symbol.append({"symbol": symbol, "notional": market_value})
            net += market_value
            gross += abs(market_value)
        return {"net": net, "gross": gross, "by_symbol": by_symbol}


_broker: Optional[BrokerService] = None
_stream: Optional[StreamService] = None
_strategy: Optional[StrategyRegistryService] = None
_risk: Optional[RiskConfigService] = None
_orchestrator: Optional[OrchestratorSupervisor] = None
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


def get_stream_manager() -> StreamService:
    global _stream
    if _stream is None:
        _stream = make_stream_service(get_runtime_flags())
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


def get_orchestrator() -> OrchestratorSupervisor:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = OrchestratorSupervisor(_kill_switch)
    return _orchestrator


def get_metrics() -> MetricsService:
    global _metrics
    if _metrics is None:
        _metrics = MetricsService()
    return _metrics
