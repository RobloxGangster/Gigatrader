from __future__ import annotations
import os
from pathlib import Path
from typing import Optional


class KillSwitch:
    """
    File-based kill switch.
    - If 'path' is provided, use it.
    - Else if KILL_SWITCH_FILE is set, use that.
    - Else default to './.kill_switch'.
    Provides both sync and async helpers so it can be used in any code path.
    """

    def __init__(self, path: Optional[os.PathLike[str] | str] = None):
        env_path = os.getenv("KILL_SWITCH_FILE")
        self.path = Path(path if path is not None else (env_path if env_path else ".kill_switch"))

    # ---------- sync ----------
    def engage_sync(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.write_text("halt", encoding="utf-8")
        except Exception:
            # best-effort fallback
            with open(self.path, "w", encoding="utf-8") as f:
                f.write("halt")

    def reset_sync(self) -> None:
        try:
            if self.path.exists():
                self.path.unlink()
        except Exception:
            pass

    def engaged_sync(self) -> bool:
        return self.path.exists()

    # ---------- async wrappers ----------
    async def engage(self) -> None:
        self.engage_sync()

    async def reset(self) -> None:
        self.reset_sync()

    async def engaged(self) -> bool:
        return self.engaged_sync()
