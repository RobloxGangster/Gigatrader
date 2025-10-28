from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class KillSwitch:
    """
    File-based kill switch.
    - If 'path' is provided, use it.
    - Else if KILL_SWITCH_FILE is set, use that.
    - Else default to './.kill_switch'.
    Provides both sync and async helpers so it can be used in any code path.

    The file now stores a small JSON payload so we can persist metadata such as
    the most recent reason or timestamp when the kill switch was engaged. Legacy
    callers that only check for file existence continue to work unchanged.
    """

    def __init__(self, path: Optional[os.PathLike[str] | str] = None):
        env_path = os.getenv("KILL_SWITCH_FILE")
        self.path = Path(path if path is not None else (env_path if env_path else ".kill_switch"))

    # ---------- sync ----------
    def engage_sync(self, reason: Optional[str] = None) -> None:
        payload = {
            "engaged": True,
            "reason": reason or "manual",
            "engaged_at": _iso_now(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except Exception:
            # best-effort fallback
            with open(self.path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False))

    def reset_sync(self) -> None:
        try:
            if self.path.exists():
                self.path.unlink()
        except Exception:
            pass

    def engaged_sync(self) -> bool:
        return self.path.exists()

    def info_sync(self) -> Dict[str, Any]:
        """Return metadata about the kill switch if available."""

        if not self.path.exists():
            return {"engaged": False, "reason": None, "engaged_at": None}
        try:
            raw = self.path.read_text(encoding="utf-8")
        except Exception:
            return {"engaged": True, "reason": None, "engaged_at": None}
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                engaged = bool(data.get("engaged", True))
                reason = data.get("reason") if isinstance(data.get("reason"), str) else None
                engaged_at = data.get("engaged_at") if isinstance(data.get("engaged_at"), str) else None
                return {"engaged": engaged, "reason": reason, "engaged_at": engaged_at}
        except Exception:
            pass
        # Fallback for legacy payloads that only wrote the string "halt".
        return {"engaged": True, "reason": None, "engaged_at": None}

    def reason_sync(self) -> Optional[str]:
        return self.info_sync().get("reason")

    def engaged_at_sync(self) -> Optional[str]:
        return self.info_sync().get("engaged_at")

    # ---------- async wrappers ----------
    async def engage(self, reason: Optional[str] = None) -> None:
        self.engage_sync(reason=reason)

    async def reset(self) -> None:
        self.reset_sync()

    async def engaged(self) -> bool:
        return self.engaged_sync()

    async def info(self) -> Dict[str, Any]:
        return self.info_sync()
