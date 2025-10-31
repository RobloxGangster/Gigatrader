from __future__ import annotations

from ui.lib.refresh import safe_autorefresh


def auto_refresh(interval_ms: int, key: str) -> None:
    """Backward-compatible wrapper retained for legacy imports."""

    safe_autorefresh(interval_ms, key=key)


__all__ = ["auto_refresh"]
