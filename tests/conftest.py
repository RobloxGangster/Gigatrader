"""Shared pytest fixtures and helpers for Gigatrader."""

from __future__ import annotations

import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterator

if TYPE_CHECKING:
    from services.risk.engine import RiskManager
    from services.risk.state import InMemoryState

import pytest

# Ensure the repository root is always importable before tests import modules.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers once at session start."""

    config.addinivalue_line("markers", "slow: marks tests that exercise long-running paths")
    config.addinivalue_line("markers", "net: marks tests that would require real network access")


@pytest.fixture(autouse=True)
def _deterministic_seed() -> Iterator[None]:
    """Reset global random state for deterministic tests."""

    random.seed(1337)
    try:
        import numpy as np
    except ModuleNotFoundError:  # pragma: no cover - optional dependency
        np = None
    if np is not None:
        np.random.seed(1337)
    yield


@pytest.fixture(autouse=True)
def _paper_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default all executions to paper mode during the test suite."""

    monkeypatch.setenv("ALPACA_PAPER", "true")
    monkeypatch.delenv("LIVE_CONFIRM", raising=False)


@pytest.fixture
def state() -> "InMemoryState":
    from services.risk.state import InMemoryState

    return InMemoryState()


@pytest.fixture
def risk_manager(state: "InMemoryState") -> "RiskManager":
    from services.risk.engine import RiskManager

    return RiskManager(state)


@dataclass
class FakeTrade:
    id: str
    status: str
    client_order_id: str
    payload: Dict[str, Any]


class DummyAlpacaAdapter:
    """Minimal async adapter used in unit tests to avoid real API calls."""

    def __init__(self) -> None:
        self.orders: Dict[str, FakeTrade] = {}
        self.counter = 0

    async def submit_order(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.counter += 1
        order_id = f"order-{self.counter}"
        trade = FakeTrade(order_id, "accepted", payload.get("client_order_id", order_id), payload)
        self.orders[order_id] = trade
        return {"id": trade.id, "status": trade.status, "client_order_id": trade.client_order_id}

    async def cancel_order(self, order_id: str) -> None:  # pragma: no cover - defensive
        self.orders.pop(order_id, None)

    async def replace_order(self, order_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        trade = self.orders.setdefault(
            order_id,
            FakeTrade(order_id, "accepted", payload.get("client_order_id", order_id), payload),
        )
        trade.payload.update(payload)
        return {"id": trade.id, "status": "replaced"}


@pytest.fixture
def fake_alpaca_adapter() -> DummyAlpacaAdapter:
    return DummyAlpacaAdapter()


class DummyOptionGateway:
    """No-op option gateway that records the last intent for assertions."""

    def __init__(self) -> None:
        self.last_intent: Dict[str, Any] | None = None

    async def propose_option_trade(self, symbol: str, side: str, qty: int) -> Dict[str, Any]:
        self.last_intent = {"symbol": symbol, "side": side, "qty": qty}
        return {"accepted": True, "client_order_id": "opt-mock"}


@pytest.fixture
def fake_option_gateway() -> DummyOptionGateway:
    return DummyOptionGateway()
