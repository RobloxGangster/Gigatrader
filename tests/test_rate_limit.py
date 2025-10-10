"""Tests for rate limit helper."""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

import pytest

from app.rate_limit import RateLimitError, backoff_request


class FakeErr(Exception):
    def __init__(self, status_code: int, headers: dict[str, str] | None = None) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code
        self.headers = headers or {}


async def ok() -> int:
    await asyncio.sleep(0)
    return 42


async def always_429() -> None:
    await asyncio.sleep(0)
    raise FakeErr(429, {"Retry-After": "0.01"})


def make_two_429_then_ok() -> Callable[[], Awaitable[str]]:
    counter = {"n": 0}

    async def _impl() -> str:
        await asyncio.sleep(0)
        if counter["n"] < 2:
            counter["n"] += 1
            raise FakeErr(429)
        return "ok"

    return _impl


@pytest.mark.asyncio
async def test_success() -> None:
    assert await backoff_request(ok) == 42


@pytest.mark.asyncio
async def test_retries_then_ok() -> None:
    fn = make_two_429_then_ok()
    assert await backoff_request(fn) == "ok"


@pytest.mark.asyncio
async def test_max_retries() -> None:
    with pytest.raises(RateLimitError):
        await backoff_request(always_429, max_retries=2)
