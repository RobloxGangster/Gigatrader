from __future__ import annotations

import pytest

from risk.manager import ConfiguredRiskManager
from core.kill_switch import KillSwitch


@pytest.mark.asyncio
async def test_position_caps_never_exceeded(tmp_path) -> None:
    kill = KillSwitch(tmp_path / "kill")
    manager = ConfiguredRiskManager(
        {
            "daily_loss_limit": 1000,
            "per_trade_loss_limit": 100,
            "max_exposure": 1000,
            "max_positions": 1,
            "options_max_notional_per_expiry": 500,
            "min_option_liquidity": 10,
            "delta_bounds": (0.2, 0.4),
            "vega_limit": 1.0,
            "theta_limit": 1.0,
        },
        kill,
    )
    portfolio = {"daily_loss": 0, "open_positions": 1}
    decision = await manager.pre_trade_check({"symbol": "MSFT", "notional": 100}, portfolio)
    assert not decision.allow
