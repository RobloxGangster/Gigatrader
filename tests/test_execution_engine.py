import asyncio
import pytest

from services.execution.engine import ExecutionEngine
from services.execution.types import ExecIntent
from services.risk.engine import RiskManager
from services.risk.state import InMemoryState


class FakeAdapter:
    def __init__(self) -> None:
        self.submits = []
        self.cancels = []
        self.replaces = []
        self.counter = 0

    async def submit_order(self, payload):
        self.submits.append(payload)
        self.counter += 1
        order_id = f"order-{self.counter}"
        return {"id": order_id, "status": "accepted", "client_order_id": payload["client_order_id"]}

    async def cancel_order(self, order_id):
        self.cancels.append(order_id)

    async def replace_order(self, order_id, payload):
        self.replaces.append((order_id, payload))
        return {"id": order_id, "status": "replaced"}


def _run(coro):
    return asyncio.run(coro)


def test_happy_path_bracket_and_risk_ok(monkeypatch):
    monkeypatch.setenv("DEFAULT_TP_PCT", "1.0")
    monkeypatch.setenv("DEFAULT_SL_PCT", "0.5")
    state = InMemoryState()
    risk = RiskManager(state)
    adapter = FakeAdapter()
    engine = ExecutionEngine(risk=risk, state=state, adapter=adapter)

    intent = ExecIntent(symbol="AAPL", side="buy", qty=10, limit_price=100.0, asset_class="equity")
    result = _run(engine.submit(intent))

    assert result.accepted is True
    assert result.client_order_id is not None
    payload = adapter.submits[0]
    assert payload["client_order_id"] == result.client_order_id
    assert payload["take_profit"]["limit_price"] == pytest.approx(101.0)
    assert payload["stop_loss"]["stop_price"] == pytest.approx(99.5)


def test_idempotency_blocks_duplicates():
    state = InMemoryState()
    risk = RiskManager(state)
    adapter = FakeAdapter()
    engine = ExecutionEngine(risk=risk, state=state, adapter=adapter)

    intent = ExecIntent(symbol="MSFT", side="buy", qty=5, limit_price=50.0)
    first = _run(engine.submit(intent))
    second = _run(engine.submit(intent))

    assert first.accepted is True
    assert second.accepted is False
    assert second.reason == "duplicate_intent"
    assert second.client_order_id == first.client_order_id


def test_risk_denial_propagates(monkeypatch):
    state = InMemoryState()
    state.day_pnl = -5000.0
    monkeypatch.setenv("DAILY_LOSS_LIMIT", "1000")
    risk = RiskManager(state)
    adapter = FakeAdapter()
    engine = ExecutionEngine(risk=risk, state=state, adapter=adapter)

    intent = ExecIntent(symbol="SPY", side="buy", qty=1, limit_price=1.0)
    result = _run(engine.submit(intent))

    assert result.accepted is False
    assert result.reason.startswith("risk_denied:")


def test_process_updates_reconciles_state(monkeypatch):
    state = InMemoryState()
    risk = RiskManager(state)
    adapter = FakeAdapter()
    engine = ExecutionEngine(risk=risk, state=state, adapter=adapter)

    intent = ExecIntent(symbol="AAPL", side="buy", qty=2, limit_price=100.0)
    submit_result = _run(engine.submit(intent))
    order_info = engine._orders[submit_result.client_order_id]

    _run(
        engine.process_update(
            {
                "event": "partial_fill",
            "order": {
                "id": order_info["alpaca_order_id"],
                "client_order_id": submit_result.client_order_id,
                "symbol": "AAPL",
                "side": "buy",
                "filled_qty": "1",
                "fill_price": "100",
                "status": "partially_filled",
                "asset_class": "us_equity",
            },
            "timestamp": 1_700_000_000.0,
            "realized_pl": "1.0",
        }
        )
    )

    assert state.positions["AAPL"].qty == pytest.approx(1.0)
    assert state.portfolio_notional == pytest.approx(100.0)
    assert state.day_pnl == pytest.approx(1.0)

    _run(
        engine.process_update(
            {
                "event": "fill",
            "order": {
                "id": order_info["alpaca_order_id"],
                "client_order_id": submit_result.client_order_id,
                "symbol": "AAPL",
                "side": "buy",
                "filled_qty": "2",
                "fill_price": "101",
                "status": "filled",
                "asset_class": "us_equity",
            },
            "timestamp": 1_700_000_010.0,
            "realized_pl": "2.5",
        }
        )
    )

    assert state.positions["AAPL"].qty == pytest.approx(2.0)
    assert state.positions["AAPL"].notional == pytest.approx(202.0)
    assert state.portfolio_notional == pytest.approx(202.0)
    assert state.day_pnl == pytest.approx(3.5)
    assert state.last_trade_ts_by_symbol["AAPL"] == pytest.approx(1_700_000_010.0)
