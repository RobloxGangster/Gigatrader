"""Centralized rate limited queue with backoff."""
from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

import logging

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RateLimitState:
    remaining: Optional[int]
    reset_time: Optional[float]


class RateLimitedQueue:
    """Async queue that enforces broker API rate limits."""

    def __init__(self, max_concurrency: int = 5) -> None:
        self._queue: asyncio.Queue[Callable[[], Awaitable[None]]] = asyncio.Queue()
        self._state = RateLimitState(remaining=None, reset_time=None)
        self._max_concurrency = max_concurrency
        self._workers: list[asyncio.Task[None]] = []
        self._lock = asyncio.Lock()
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        for _ in range(self._max_concurrency):
            self._workers.append(asyncio.create_task(self._worker()))

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        for _ in self._workers:
            await self._queue.put(lambda: asyncio.sleep(0))
        await asyncio.gather(*self._workers)
        self._workers.clear()

    async def submit(self, coro_factory: Callable[[], Awaitable[None]]) -> None:
        """Submit a coroutine to be executed respecting rate limits."""

        await self._queue.put(coro_factory)

    async def update_from_headers(self, headers: dict[str, str]) -> None:
        """Update internal rate limits from response headers."""

        async with self._lock:
            remaining = headers.get("X-RateLimit-Remaining")
            reset = headers.get("X-RateLimit-Reset")
            self._state.remaining = int(remaining) if remaining else None
            self._state.reset_time = float(reset) if reset else None

    async def _worker(self) -> None:
        while self._running:
            coro_factory = await self._queue.get()
            if not self._running:
                break
            await self._throttle()
            try:
                await coro_factory()
            except Exception as exc:  # noqa: BLE001 - intentional top-level catch
                logger.exception("Rate-limited task failed", exc_info=exc)
            self._queue.task_done()

    async def _throttle(self) -> None:
        async with self._lock:
            remaining = self._state.remaining
            reset_time = self._state.reset_time
        if remaining is not None and remaining <= 0 and reset_time:
            delay = max(0.0, reset_time - time.time())
            jitter = random.uniform(0, 1)
            await asyncio.sleep(delay + jitter)
        else:
            await asyncio.sleep(random.uniform(0, 0.1))
