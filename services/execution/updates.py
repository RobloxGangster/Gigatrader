"""Order update streaming abstractions."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict


class UpdateBus:
    """Placeholder update bus that can be swapped with a real Alpaca stream."""

    async def run(self, on_update: Callable[[Dict[str, Any]], Awaitable[None]]) -> None:
        # No-op stub for paper trading in unit tests. Real implementation will wire Alpaca streams.
        return None
