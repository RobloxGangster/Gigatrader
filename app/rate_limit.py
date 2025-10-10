"""Simple HTTP rate-limit/backoff helper."""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


class RateLimitError(Exception):
    """Raised when rate-limit retries are exhausted."""


def _extract_retry_after(headers: object) -> float | None:
    if not isinstance(headers, dict):
        return None
    retry_after = headers.get("Retry-After")
    if retry_after is None:
        return None
    try:
        return float(retry_after)
    except (TypeError, ValueError):
        return None


async def backoff_request(fn: Callable[[], Awaitable[T]], max_retries: int = 5) -> T:
    """Execute an async HTTP call, backing off on HTTP 429 responses."""

    delay = 1.0
    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except Exception as exc:  # pragma: no cover - specific client errors not available
            status = getattr(exc, "status_code", None)
            headers = getattr(exc, "headers", {})
            if status == 429:
                retry_after = _extract_retry_after(headers)
                if retry_after is not None:
                    delay = max(delay, retry_after)
                if attempt == max_retries:
                    raise RateLimitError("Max retries exceeded after 429 responses") from exc
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)
                continue
            raise
    raise RateLimitError("Max retries exceeded after 429 responses")
