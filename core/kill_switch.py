"""Global kill switch implementation."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

KILL_SWITCH_ENV = "TRADE_HALT"
DISABLE_KILL_SWITCH_ENV = "DISABLE_KILL_SWITCH_FOR_TESTS"
DEFAULT_KILL_FILE = Path(".kill_switch")


def _kill_switch_disabled() -> bool:
    return os.getenv(DISABLE_KILL_SWITCH_ENV, "").lower() in {"1", "true", "yes"}


def is_active(path: Path = DEFAULT_KILL_FILE) -> bool:
    """Return True when the kill switch should halt trading."""

    if _kill_switch_disabled():
        return False
    env_active = os.getenv(KILL_SWITCH_ENV, "false").lower() == "true"
    return env_active or path.exists()


class KillSwitch:
    """Tracks global halt state with file + env flag."""

    def __init__(self, path: Path = DEFAULT_KILL_FILE) -> None:
        self._path = path
        self._lock = asyncio.Lock()

    async def engaged(self) -> bool:
        """Return whether the switch is active."""

        return is_active(self._path)

    async def engage(self) -> None:
        """Activate the kill switch."""

        async with self._lock:
            self._path.touch()
            os.environ[KILL_SWITCH_ENV] = "true"

    async def reset(self) -> None:
        """Deactivate the kill switch."""

        async with self._lock:
            if self._path.exists():
                self._path.unlink()
            os.environ.pop(KILL_SWITCH_ENV, None)
