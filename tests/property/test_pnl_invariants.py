from __future__ import annotations

import asyncio

from backtest.engine import BacktestConfig, BacktestEngine
from strategies.equities_momentum import EquitiesMomentumStrategy


def test_no_positions_no_pnl() -> None:
    async def runner() -> None:
        engine = BacktestEngine([EquitiesMomentumStrategy([])], BacktestConfig())
        result = await engine.run([])
        assert result.equity_curve[-1] == 0

    asyncio.run(runner())
