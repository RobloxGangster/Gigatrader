from __future__ import annotations

import asyncio

from strategies.options_directional import OptionsDirectionalStrategy


def test_options_chain_filter_selects_contract() -> None:
    async def runner() -> None:
        strategy = OptionsDirectionalStrategy((0.3, 0.35))
        await strategy.prepare({"regime": "active"})
        chain = [
            {"symbol": "AAPL230915C00180000", "mid": 1.5, "volume": 100, "greeks": {"delta": 0.32}},
            {
                "symbol": "AAPL230915P00170000",
                "mid": 1.2,
                "volume": 200,
                "greeks": {"delta": -0.28},
            },
        ]
        orders = await strategy.on_bar({"option_chain": chain})
        assert orders[0]["symbol"] == "AAPL230915C00180000"

    asyncio.run(runner())
