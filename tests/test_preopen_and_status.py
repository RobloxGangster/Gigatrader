from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from backend import api as backend_api
from backend.routers import orchestrator as orchestrator_router
from backend.services import orchestrator as orchestrator_service
from services.strategy.engine import StrategyEngine
from services.strategy.types import Bar as StrategyBar, OrderPlan


class _StubOrchestrator:
    def __init__(self, snapshot: dict[str, object]):
        self._snapshot = snapshot

    def status(self) -> dict[str, object]:
        return dict(self._snapshot)

    def reset_kill_switch(self, *, requested_by: str) -> None:  # pragma: no cover - interface compat
        return None


class _StubOptionGateway:
    async def propose_option_trade(self, *args, **kwargs):  # pragma: no cover - not used
        return None


class _StubState:
    def mark_trade(self, *args, **kwargs):  # pragma: no cover - not used
        return None


class _StaticStrategy:
    def on_bar(self, symbol, bar, senti, regime):
        return OrderPlan(symbol=symbol, side="buy", qty=1.0)


class _StubExec:
    def __init__(self):
        self.intents = []

    async def submit(self, intent):
        self.intents.append(intent)
        return None


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch):
    monkeypatch.delenv("ALLOW_PREOPEN", raising=False)
    monkeypatch.delenv("PREOPEN_PLACE_MINUTES", raising=False)
    monkeypatch.delenv("DEFAULT_OPEN_ORDER_KIND", raising=False)
    monkeypatch.delenv("STRAT_OPTION_ENABLED", raising=False)
    yield


def test_status_shape(monkeypatch):
    snapshot = {
        "state": "running",
        "running": True,
        "transition": None,
        "phase": "running",
        "restart_count": 0,
        "uptime_secs": 0.1,
        "thread_alive": True,
    }
    stub = _StubOrchestrator(snapshot)
    monkeypatch.setattr(orchestrator_router, "get_orchestrator", lambda: stub)
    monkeypatch.setattr(
        orchestrator_router.orchestrator_manager,
        "get_status",
        lambda: {"state": "running", "thread_alive": True},
    )
    client = TestClient(backend_api.app)
    response = client.get("/orchestrator/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] in {"running", "stopped"}
    assert "transition" in payload
    assert payload["phase"] == "running"


@pytest.mark.asyncio
async def test_preopen_opg_order(monkeypatch):
    monkeypatch.setenv("ALLOW_PREOPEN", "true")
    monkeypatch.setenv("PREOPEN_PLACE_MINUTES", "5")
    monkeypatch.setenv("DEFAULT_OPEN_ORDER_KIND", "market")
    monkeypatch.setenv("STRAT_OPTION_ENABLED", "false")

    decisions: list[tuple[str, dict]] = []
    exec_stub = _StubExec()

    def _record_decision(**kwargs):
        decisions.append(("decision", kwargs))

    monkeypatch.setattr("services.strategy.engine.record_decision_cycle", _record_decision)
    monkeypatch.setattr("services.strategy.engine.market_is_open", lambda _now=None: False)
    monkeypatch.setattr("services.strategy.engine.seconds_until_open", lambda _now=None: 60.0)

    await orchestrator_service.drain_preopen_queue()

    engine = StrategyEngine(
        exec_engine=exec_stub,
        option_gateway=_StubOptionGateway(),
        state=_StubState(),
        equity_strategies=[_StaticStrategy()],
        option_strategies=[],
    )

    bar = StrategyBar(ts=datetime.utcnow().timestamp(), open=100.0, high=101.0, low=99.0, close=100.5, volume=1000.0)
    await engine.on_bar("AAPL", bar, senti=0.6)

    assert not exec_stub.intents
    queue_count = orchestrator_service.get_preopen_queue_count()
    assert queue_count >= 1
    assert decisions
    assert decisions[-1][0] == "decision"
    assert decisions[-1][1]["preopen_queue"] >= 1

    await orchestrator_service.drain_preopen_queue()


def test_ui_refresh_does_not_stop_worker(monkeypatch):
    snapshot = {
        "state": "stopped",
        "phase": "stopped",
        "running": False,
        "transition": None,
        "restart_count": 0,
        "uptime_secs": 0.0,
        "thread_alive": False,
    }
    stub = _StubOrchestrator(snapshot)
    monkeypatch.setattr(orchestrator_router, "get_orchestrator", lambda: stub)
    monkeypatch.setattr(
        orchestrator_router.orchestrator_manager,
        "get_status",
        lambda: {"state": "stopped", "thread_alive": False},
    )
    stop_calls: list[str] = []
    monkeypatch.setattr(
        orchestrator_router.orchestrator_manager,
        "stop",
        lambda reason="requested_stop": stop_calls.append(reason) or {"state": "stopped"},
    )
    client = TestClient(backend_api.app)
    response = client.get("/orchestrator/status")
    assert response.status_code == 200
    assert stop_calls == []
