from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.signals.signal_engine import SignalBundle
from app.trade.orchestrator import TradeOrchestrator
from app.execution.router import ExecIntent
from core.config import TradeLoopConfig
from core.runtime_flags import RuntimeFlags


@dataclass
class StubSignalGenerator:
    failures: int = 0

    def __post_init__(self) -> None:
        self.calls = 0

    def produce(self, profile: str, universe: list[str]) -> SignalBundle:
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("transient failure")
        return SignalBundle(
            generated_at=datetime.utcnow(),
            profile=profile,
            candidates=[],
        )


class StubRiskManager:
    def __init__(self) -> None:
        self.state = SimpleNamespace(get_account_equity=lambda: 100000)

    def pre_trade_check(self, proposal):  # pragma: no cover - simple allow
        return SimpleNamespace(allow=True)

    def _risk_budget_dollars(self) -> float:  # pragma: no cover - constant
        return 1000.0


class StubRouter:
    def __init__(self) -> None:
        self.mock_mode = False
        self.submissions: list[ExecIntent] = []

    def submit(self, intent: ExecIntent, dry_run: bool = False):  # pragma: no cover - no routing
        self.submissions.append(intent)
        return {"accepted": True, "dry_run": dry_run}


class StubDataClient:  # pragma: no cover - placeholder
    pass


FLAGS = RuntimeFlags(
    mock_mode=False,
    broker_mode="paper",
    paper_trading=True,
    auto_restart=True,
    api_base_url="http://localhost",
    api_port=8000,
    ui_port=8501,
    alpaca_base_url="https://paper-api.alpaca.markets",
    alpaca_key=None,
    alpaca_secret=None,
)


@pytest.mark.asyncio
async def test_orchestrator_empty_candidates_keeps_running():
    generator = StubSignalGenerator()
    orchestrator = TradeOrchestrator(
        data_client=StubDataClient(),
        signal_generator=generator,
        ml_predictor=None,
        risk_manager=StubRiskManager(),
        router=StubRouter(),
        config=TradeLoopConfig(interval_sec=0.01, universe=["AAPL"]),
        flags=FLAGS,
    )
    await orchestrator.start()
    await asyncio.sleep(0.05)
    status = orchestrator.status()
    assert status["running"] is True
    assert generator.calls > 0
    await orchestrator.stop()


@pytest.mark.asyncio
async def test_orchestrator_auto_restarts_on_failure():
    generator = StubSignalGenerator(failures=1)
    orchestrator = TradeOrchestrator(
        data_client=StubDataClient(),
        signal_generator=generator,
        ml_predictor=None,
        risk_manager=StubRiskManager(),
        router=StubRouter(),
        config=TradeLoopConfig(interval_sec=0.01, universe=["MSFT"]),
        flags=FLAGS,
    )
    await orchestrator.start()
    await asyncio.sleep(1.2)
    status = orchestrator.status()
    assert generator.calls >= 2
    assert status["running"] is True
    assert status["last_error"] is None
    await orchestrator.stop()


@pytest.mark.asyncio
async def test_orchestrator_status_reports_last_error():
    failing_flags = RuntimeFlags(**{**FLAGS.__dict__, "auto_restart": False})
    generator = StubSignalGenerator(failures=3)
    orchestrator = TradeOrchestrator(
        data_client=StubDataClient(),
        signal_generator=generator,
        ml_predictor=None,
        risk_manager=StubRiskManager(),
        router=StubRouter(),
        config=TradeLoopConfig(interval_sec=0.01, universe=["TSLA"]),
        flags=failing_flags,
    )
    await orchestrator.start()
    await asyncio.sleep(0.05)
    status = orchestrator.status()
    assert status["last_error"] is not None
    await orchestrator.stop()
