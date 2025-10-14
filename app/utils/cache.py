from __future__ import annotations

import threading
import time
from collections.abc import Hashable
from typing import Generic, TypeVar

T = TypeVar("T")


class TTLCache(Generic[T]):
    """A very small in-memory TTL cache suitable for single-process use."""

    def __init__(self, ttl_seconds: float = 2.0) -> None:
        self._ttl = ttl_seconds
        self._store: dict[Hashable, tuple[float, T]] = {}
        self._lock = threading.Lock()

    def get(self, key: Hashable) -> T | None:
        now = time.monotonic()
        with self._lock:
            item = self._store.get(key)
            if not item:
                return None
            expires, value = item
            if expires <= now:
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: Hashable, value: T) -> None:
        expires = time.monotonic() + self._ttl
        with self._lock:
            self._store[key] = (expires, value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
