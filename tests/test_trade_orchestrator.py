import asyncio
from datetime import datetime
import types

import pytest

from app.trade.orchestrator import TradeOrchestrator
from app.signals.signal_engine import SignalBundle, SignalCandidate
from core.config import TradeLoopConfig
from services.risk.engine import Decision


class StubSignalGenerator:
    def __init__(self, candidates):
        self._candidates = candidates
        self.calls = 0

    def produce(self, profile: str = "balanced", universe=None):  # noqa: D401 - stub
        self.calls += 1
        if self.calls > 1:
            return SignalBundle(generated_at=datetime.utcnow(), profile=profile, candidates=[])
        return SignalBundle(generated_at=datetime.utcnow(), profile=profile, candidates=list(self._candidates))


class StubMLPredictor:
    def __init__(self, mapping):
        self.mapping = {k.upper(): v for k, v in mapping.items()}
        self.calls = 0

    def predict(self, symbols):
        self.calls += 1
        if isinstance(symbols, str):
            return self.mapping.get(symbols.upper(), 0.5)
        return {sym.upper(): self.mapping.get(sym.upper(), 0.5) for sym in symbols}


class StubRiskManager:
    def __init__(self, rejects=None):
        self.rejects = rejects or {}
        self.calls = []

    def pre_trade_check(self, proposal):
        self.calls.append(proposal)
        reason = self.rejects.get(proposal.symbol)
        if reason:
            return Decision(False, reason)
        return Decision(True, "ok")

    def _risk_budget_dollars(self):
        return 1_000.0


class StubRouter:
    def __init__(self, responses, configured=True):
        self.responses = list(responses)
        self.calls = []
        self.broker = types.SimpleNamespace(is_configured=lambda: configured)

    def submit(self, intent, dry_run=False):
        self.calls.append(types.SimpleNamespace(intent=intent, dry_run=dry_run))
        if self.responses:
            response = self.responses.pop(0)
        else:
            response = {"accepted": True, "client_order_id": "cid"}
        return response


def _candidate(symbol: str, confidence: float, entry: float, stop: float, target: float, side: str = "buy"):
    return SignalCandidate(
        kind="equity",
        symbol=symbol,
        side=side,
        entry=entry,
        stop=stop,
        target=target,
        confidence=confidence,
        rationale="test",
        meta={},
    )


@pytest.mark.asyncio
async def test_trade_orchestrator_routes_top_ev():
    candidates = [
        _candidate("AAPL", 0.7, 100.0, 95.0, 104.0),
        _candidate("MSFT", 0.8, 120.0, 115.0, 130.0),
    ]
    signal_gen = StubSignalGenerator(candidates)
    ml = StubMLPredictor({"AAPL": 0.52, "MSFT": 0.68})
    risk = StubRiskManager()
    router = StubRouter(
        [
            {"accepted": False, "reason": "broker_error:duplicate_client_order_id"},
            {"accepted": True, "client_order_id": "cid-1"},
        ],
        configured=True,
    )

    config = TradeLoopConfig(
        interval_sec=0.01,
        top_n=1,
        min_conf=0.0,
        min_ev=-10.0,
        universe=["AAPL", "MSFT"],
    )

    orchestrator = TradeOrchestrator(
        data_client=None,
        signal_generator=signal_gen,
        ml_predictor=ml,
        risk_manager=risk,
        router=router,
        config=config,
    )

    try:
        await orchestrator.start()
        await asyncio.sleep(0.05)
        snapshot = orchestrator.status()
        assert snapshot["running"] is True
    finally:
        await orchestrator.stop()

    assert len(router.calls) == 2
    assert router.calls[0].intent.symbol == "MSFT"
    decisions = orchestrator.last_decisions()
    accepted = [d for d in decisions if d.get("status") == "accepted"]
    assert any(d["symbol"] == "MSFT" for d in accepted)
    skipped = [d for d in decisions if d.get("status") == "skipped"]
    assert any(d["symbol"] == "AAPL" for d in skipped)


@pytest.mark.asyncio
async def test_trade_orchestrator_respects_thresholds_and_risk():
    candidates = [
        _candidate("AAPL", 0.3, 50.0, 48.0, 54.0),
        _candidate("MSFT", 0.9, 60.0, 57.0, 70.0),
    ]
    signal_gen = StubSignalGenerator(candidates)
    risk = StubRiskManager(rejects={"MSFT": "kill_switch_active"})
    router = StubRouter([], configured=True)

    config = TradeLoopConfig(
        interval_sec=0.01,
        top_n=2,
        min_conf=0.5,
        min_ev=-5.0,
        universe=["AAPL", "MSFT"],
    )

    orchestrator = TradeOrchestrator(
        data_client=None,
        signal_generator=signal_gen,
        ml_predictor=None,
        risk_manager=risk,
        router=router,
        config=config,
    )

    try:
        await orchestrator.start()
        await asyncio.sleep(0.05)
    finally:
        await orchestrator.stop()

    assert len(router.calls) == 0
    decisions = orchestrator.last_decisions()
    low_conf = next(d for d in decisions if d["symbol"] == "AAPL")
    assert low_conf["status"] == "filtered"
    assert "confidence_below_min" in low_conf.get("filters", [])
    risk_block = next(d for d in decisions if d["symbol"] == "MSFT")
    assert risk_block["status"] == "rejected"
    assert any("risk:kill_switch_active" in f for f in risk_block.get("filters", []))


@pytest.mark.asyncio
async def test_trade_orchestrator_handles_router_failures():
    candidates = [_candidate("NVDA", 0.9, 200.0, 195.0, 220.0)]
    signal_gen = StubSignalGenerator(candidates)
    risk = StubRiskManager()
    router = StubRouter(
        [
            {"accepted": False, "reason": "broker_error:alpaca_unauthorized"},
            {"accepted": False, "dry_run": True, "client_order_id": "mock"},
        ],
        configured=True,
    )

    config = TradeLoopConfig(
        interval_sec=0.01,
        top_n=1,
        min_conf=0.0,
        min_ev=-5.0,
        universe=["NVDA"],
    )

    orchestrator = TradeOrchestrator(
        data_client=None,
        signal_generator=signal_gen,
        ml_predictor=None,
        risk_manager=risk,
        router=router,
        config=config,
    )

    try:
        await orchestrator.start()
        await asyncio.sleep(0.05)
        snapshot = orchestrator.status()
        assert snapshot["broker"]["mock_mode"] is True
        assert snapshot["broker"]["disabled"] is True
    finally:
        await orchestrator.stop()

    decisions = orchestrator.last_decisions()
    assert any("alpaca_unauthorized" in ":".join(d.get("filters", [])) for d in decisions)
