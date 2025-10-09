from __future__ import annotations

import pytest

from backtest.engine import BacktestConfig, BacktestEngine


class DummyStrategy:
    async def prepare(self, data_context):
        return None

    async def on_bar(self, event):
        return [{"qty": 1, "limit_price": event.get("close", 0), "symbol": event.get("symbol", "TEST")}]

    async def on_fill(self, event):
        return None


@pytest.mark.asyncio
async def test_backtester_fill_conservation() -> None:
    engine = BacktestEngine([DummyStrategy()], BacktestConfig(latency_ms=0))
    bars = [{"symbol": "TEST", "close": 10.0} for _ in range(3)]
    result = await engine.run(bars)
    assert len(result.trades) == len(bars)
