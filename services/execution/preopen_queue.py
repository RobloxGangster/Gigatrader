"""Concurrency-safe queue for pre-open execution intents."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional


@dataclass
class PreopenIntent:
    symbol: str
    side: str  # "buy" or "sell"
    qty: int
    order_kind: str  # "market"|"limit"
    limit_price: Optional[float] = None
    client_order_id: Optional[str] = None


class PreopenQueue:
    def __init__(self) -> None:
        self._q: Deque[PreopenIntent] = deque()
        self._lock = asyncio.Lock()

    async def enqueue(self, intent: PreopenIntent) -> None:
        async with self._lock:
            self._q.append(intent)

    async def drain(self) -> List[PreopenIntent]:
        async with self._lock:
            items = list(self._q)
            self._q.clear()
            return items

    async def count(self) -> int:
        async with self._lock:
            return len(self._q)


__all__ = ["PreopenIntent", "PreopenQueue"]
