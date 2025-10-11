"""Unit tests for the autonomous strategy engine."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import List

import pytest

from services.strategy.engine import StrategyEngine
from services.strategy.types import Bar
from services.risk.state import InMemoryState


@dataclass
class FakeResult:
    accepted: bool = True
    reason: str = "ok"
    client_order_id: str = "cid"


class FakeExec:
    """Minimal execution engine stub capturing intents."""

    def __init__(self) -> None:
        self.submits: List = []

    async def submit(self, intent):
        self.submits.append(intent)
        return FakeResult()


class FakeOptionGateway:
    """Stubbed option gateway that records proposed trades."""

    def __init__(self) -> None:
        self.calls: List[tuple[str, str, float]] = []

    async def propose_option_trade(self, underlying: str, side: str, qty: float):
        self.calls.append((underlying, side, qty))
        return {"accepted": True, "client_order_id": "cid123", "selected": "OPT"}


@pytest.fixture(autouse=True)
def clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure strategy-specific environment variables do not leak between tests."""

    keys = [
        "STRAT_SENTI_MIN",
        "STRAT_MOMENTUM_MIN_RSI",
        "STRAT_COOLDOWN_SEC",
        "STRAT_MAX_POS_PER_SYMBOL",
        "STRAT_REGIME_DISABLE_CHOPPY",
        "STRAT_EQUITY_ENABLED",
        "STRAT_OPTION_ENABLED",
        "STRAT_OPTION_MIN_VOLUME",
        "STRAT_UNIVERSE_MAX",
        "SYMBOLS",
    ]
    for key in keys:
        monkeypatch.delenv(key, raising=False)


def test_equities_signal_with_senti_and_orb(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRAT_SENTI_MIN", "0.1")
    monkeypatch.setenv("STRAT_MOMENTUM_MIN_RSI", "40")
    monkeypatch.setenv("STRAT_COOLDOWN_SEC", "0")
    monkeypatch.setenv("STRAT_EQUITY_ENABLED", "true")
    monkeypatch.setenv("STRAT_OPTION_ENABLED", "false")
    monkeypatch.setenv("SYMBOLS", "AAPL,MSFT,SPY")

    async def _run() -> None:
        state = InMemoryState()
        exec_engine = FakeExec()
        option_gateway = FakeOptionGateway()
        engine = StrategyEngine(exec_engine, option_gateway, state)

        bar_base = Bar(ts=1, open=100, high=101, low=99, close=100, volume=1_000_000)
        for _ in range(30):
            await engine.on_bar("AAPL", bar_base, senti=0.2)

        breakout_bar = Bar(ts=2, open=100, high=102, low=99.5, close=101.5, volume=1_200_000)
        await engine.on_bar("AAPL", breakout_bar, senti=0.25)

        assert any(intent.symbol == "AAPL" for intent in exec_engine.submits)

    asyncio.run(_run())


def test_options_signal_calls_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRAT_COOLDOWN_SEC", "0")
    monkeypatch.setenv("STRAT_OPTION_ENABLED", "true")
    monkeypatch.setenv("STRAT_EQUITY_ENABLED", "false")
    monkeypatch.setenv("STRAT_OPTION_MIN_VOLUME", "0")
    monkeypatch.setenv("SYMBOLS", "AAPL,MSFT,SPY")

    async def _run() -> None:
        state = InMemoryState()
        exec_engine = FakeExec()
        option_gateway = FakeOptionGateway()
        engine = StrategyEngine(exec_engine, option_gateway, state)

        bar = Bar(ts=1, open=100, high=101, low=99, close=100.5, volume=1_000_000)
        await engine.on_bar("MSFT", bar, senti=0.3)

        assert option_gateway.calls and option_gateway.calls[0][0] == "MSFT"

    asyncio.run(_run())
