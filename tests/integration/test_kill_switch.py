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


def test_kill_switch_reason_metadata(tmp_path) -> None:
    kill = KillSwitch(tmp_path / "halt_meta")
    info = kill.info_sync()
    assert info["engaged"] is False
    assert info["reason"] is None

    kill.engage_sync(reason="manual_test")
    engaged = kill.info_sync()
    assert engaged["engaged"] is True
    assert engaged["reason"] == "manual_test"
    assert isinstance(engaged.get("engaged_at"), str)

    kill.reset_sync()
    reset_info = kill.info_sync()
    assert reset_info["engaged"] is False
