from __future__ import annotations

import asyncio

import pytest

from core.rate_limiter import RateLimitedQueue


@pytest.mark.asyncio
async def test_rate_limiter_executes_tasks() -> None:
    queue = RateLimitedQueue(max_concurrency=1)
    await queue.start()
    executed: list[int] = []

    async def worker(idx: int) -> None:
        executed.append(idx)

    await queue.submit(lambda idx=1: worker(idx))
    await asyncio.sleep(0.2)
    await queue.stop()
    assert executed == [1]


@pytest.mark.asyncio
async def test_rate_limiter_updates_from_headers() -> None:
    queue = RateLimitedQueue(max_concurrency=1)
    await queue.update_from_headers({"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "0"})
    # internal state should trigger throttle path without raising
    await queue.start()

    async def noop() -> None:
        return None

    await queue.submit(lambda: noop())
    await asyncio.sleep(0.1)
    await queue.stop()
