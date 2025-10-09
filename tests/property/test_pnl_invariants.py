from __future__ import annotations

import asyncio

import pytest

from backtest.engine import BacktestConfig, BacktestEngine
from strategies.equities_momentum import EquitiesMomentumStrategy


@pytest.mark.asyncio
async def test_no_positions_no_pnl() -> None:
    engine = BacktestEngine([EquitiesMomentumStrategy([])], BacktestConfig())
    result = await engine.run([])
    assert result.equity_curve[-1] == 0
