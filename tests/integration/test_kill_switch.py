from __future__ import annotations

import asyncio

import pytest

from core.kill_switch import KillSwitch


@pytest.mark.asyncio
async def test_kill_switch_engage_and_reset(tmp_path) -> None:
    kill = KillSwitch(tmp_path / "halt")
    assert not await kill.engaged()
    await kill.engage()
    assert await kill.engaged()
    await kill.reset()
    assert not await kill.engaged()
