from __future__ import annotations

import asyncio

from risk.manager import ConfiguredRiskManager
from core.kill_switch import KillSwitch


def test_kill_switch_blocks_order(tmp_path) -> None:
    async def runner() -> None:
        kill = KillSwitch(tmp_path / "kill")
        await kill.engage()
        manager = ConfiguredRiskManager(
            {
                "daily_loss_limit": 1000,
                "per_trade_loss_limit": 100,
                "max_exposure": 1000,
                "max_positions": 5,
                "options_max_notional_per_expiry": 500,
                "min_option_liquidity": 10,
                "delta_bounds": (0.2, 0.4),
                "vega_limit": 1.0,
                "theta_limit": 1.0,
            },
            kill,
        )
        decision = await manager.pre_trade_check(
            {"symbol": "AAPL", "notional": 100}, {"daily_loss": 0, "open_positions": 0}
        )
        assert not decision.allow
        assert decision.reason == "Kill switch engaged"

    asyncio.run(runner())


def test_option_liquidity_block(tmp_path) -> None:
    async def runner() -> None:
        kill = KillSwitch(tmp_path / "kill")
        await kill.reset()
        manager = ConfiguredRiskManager(
            {
                "daily_loss_limit": 1000,
                "per_trade_loss_limit": 100,
                "max_exposure": 1000,
                "max_positions": 5,
                "options_max_notional_per_expiry": 500,
                "min_option_liquidity": 10,
                "delta_bounds": (0.2, 0.4),
                "vega_limit": 1.0,
                "theta_limit": 1.0,
            },
            kill,
        )
        decision = await manager.pre_trade_check(
            {
                "symbol": "AAPL230915C00180000",
                "asset_class": "option",
                "notional": 400,
                "greeks": {"delta": 0.5, "vega": 0.2, "theta": 0.1},
                "liquidity": 5,
            },
            {"daily_loss": 0, "open_positions": 0},
        )
        assert not decision.allow
        assert decision.reason in {"Delta outside bounds", "Insufficient option liquidity"}

    asyncio.run(runner())
