"""Integration-style tests for the option gateway."""

from __future__ import annotations

import asyncio

from services.execution.engine import ExecutionEngine
from services.execution.types import ExecIntent
from services.gateway.options import OptionGateway
from services.options.chain import OptionContract
from services.risk.engine import RiskManager
from services.risk.state import InMemoryState


class FakeChain:
    async def fetch(self, underlying: str) -> list[OptionContract]:
        return [
            OptionContract(
                symbol="AAPL_2025C_100",
                underlying=underlying,
                expiry="2025-01-01",
                strike=100.0,
                side="call",  # type: ignore[arg-type]
                delta=0.31,
                iv=0.4,
                bid=2.4,
                ask=2.6,
                mid=2.5,
                volume=500,
                oi=1000,
                dte=14,
            )
        ]


class FakeExec(ExecutionEngine):
    def __init__(self, risk: RiskManager) -> None:
        self.risk = risk

    async def submit(self, intent: ExecIntent):  # type: ignore[override]
        class Result:
            accepted = True
            reason = "ok"
            client_order_id = "cid123"

        self.last_intent = intent
        return Result()


def test_gateway_happy_path() -> None:
    state = InMemoryState()
    risk = RiskManager(state)
    gateway = OptionGateway(exec_engine=FakeExec(risk), chain_source=FakeChain(), risk_manager=risk)

    result = asyncio.run(gateway.propose_option_trade("AAPL", "buy", 1))

    assert result["accepted"] is True
    assert result["client_order_id"] == "cid123"
    assert result["selected"].startswith("AAPL_")


class EmptyChain(FakeChain):
    async def fetch(self, underlying: str) -> list[OptionContract]:  # type: ignore[override]
        return []


def test_gateway_no_contract() -> None:
    state = InMemoryState()
    risk = RiskManager(state)
    gateway = OptionGateway(
        exec_engine=FakeExec(risk), chain_source=EmptyChain(), risk_manager=risk
    )

    result = asyncio.run(gateway.propose_option_trade("AAPL", "buy", 1))

    assert result["accepted"] is False
    assert result["reason"] == "no_contract_found"
