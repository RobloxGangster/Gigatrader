"""Lightweight event bus for decoupled components."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Awaitable, Callable, DefaultDict, List

EventHandler = Callable[[Any], Awaitable[None]]


class EventBus:
    """Async pub/sub event bus."""

    def __init__(self) -> None:
        self._subscribers: DefaultDict[str, List[EventHandler]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Register ``handler`` for ``event_type``."""

        async with self._lock:
            self._subscribers[event_type].append(handler)

    async def publish(self, event_type: str, payload: Any) -> None:
        """Publish ``payload`` to all subscribers."""

        handlers = list(self._subscribers.get(event_type, ()))
        await asyncio.gather(*(handler(payload) for handler in handlers))
