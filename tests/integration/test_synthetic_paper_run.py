from __future__ import annotations

import pytest

from backtest.engine import BacktestConfig, BacktestEngine
from strategies.equities_momentum import EquitiesMomentumStrategy


@pytest.mark.asyncio
async def test_synthetic_paper_run_one_day() -> None:
    strategy = EquitiesMomentumStrategy(["TEST"])
    engine = BacktestEngine([strategy], BacktestConfig(latency_ms=0))
    bars = [
        {"symbol": "TEST", "close": 10.0, "signals": {"orb_breakout": True, "momentum": 1, "size": 1, "target": 11, "stop": 9}},
    ]
    result = await engine.run(bars)
    assert result.equity_curve[-1] == result.trades[-1]["pnl"]
