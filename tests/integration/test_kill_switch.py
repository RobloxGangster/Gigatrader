from __future__ import annotations

import asyncio

from core.kill_switch import KillSwitch


def test_kill_switch_engage_and_reset(tmp_path) -> None:
    async def runner() -> None:
        kill = KillSwitch(tmp_path / "halt")
        assert not await kill.engaged()
        await kill.engage()
        assert await kill.engaged()
        await kill.reset()
        assert not await kill.engaged()

    asyncio.run(runner())
