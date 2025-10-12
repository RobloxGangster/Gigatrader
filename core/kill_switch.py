"""Global kill switch implementation."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

KILL_SWITCH_ENV = "TRADE_HALT"
DEFAULT_KILL_FILE = Path(".kill_switch")


class KillSwitch:
    """Tracks global halt state with file + env flag."""

    def __init__(self, path: Path = DEFAULT_KILL_FILE) -> None:
        self._path = path
        self._lock = asyncio.Lock()

    async def engaged(self) -> bool:
        """Return whether the switch is active."""

        env = os.getenv(KILL_SWITCH_ENV, "false").lower() == "true"
        file_state = self._path.exists()
        return env or file_state

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
