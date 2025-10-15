"""In-process telemetry helpers for trading services."""

from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncIterator, Deque, Dict, Iterator, Optional


def _percentile(sorted_values: Deque[float] | list[float], quantile: float) -> Optional[float]:
    """Return the ``quantile`` (0-1) for ``sorted_values`` using linear interpolation."""

    if not sorted_values:
        return None
    values = list(sorted_values)
    if len(values) == 1:
        return float(values[0])
    q = min(max(quantile, 0.0), 1.0)
    pos = (len(values) - 1) * q
    lower = math.floor(pos)
    upper = math.ceil(pos)
    if lower == upper:
        return float(values[int(pos)])
    lower_value = float(values[lower])
    upper_value = float(values[upper])
    weight = pos - lower
    return lower_value + (upper_value - lower_value) * weight


def _normalize_code(code: Any) -> str:
    if code is None:
        return "unknown"
    text = str(code).strip().lower()
    if not text:
        return "unknown"
    if ":" in text:
        text = text.split(":", 1)[0]
    text = text.replace(" ", "_")
    return text or "unknown"


class TelemetryMetrics:
    """Simple in-process aggregator for trading telemetry."""

    def __init__(self, *, max_latency_samples: int = 512) -> None:
        self._lock = threading.Lock()
        self._latency_samples: Deque[float] = deque(maxlen=max_latency_samples)
        self._latency_count: int = 0
        self._order_rejects: Dict[str, int] = defaultdict(int)
        self._ws_reconnects: int = 0
        self._data_staleness: Optional[float] = None

    # ------------------------------------------------------------------
    # Counters
    def observe_order_latency(self, latency_ms: float) -> None:
        latency = max(float(latency_ms), 0.0)
        with self._lock:
            self._latency_samples.append(latency)
            self._latency_count += 1

    def inc_order_reject(self, code: Any) -> None:
        key = _normalize_code(code)
        with self._lock:
            self._order_rejects[key] += 1

    def inc_ws_reconnect(self) -> None:
        with self._lock:
            self._ws_reconnects += 1

    def set_data_staleness(self, seconds: Optional[float]) -> None:
        value: Optional[float]
        if seconds is None:
            value = None
        else:
            try:
                value = max(float(seconds), 0.0)
            except (TypeError, ValueError):
                value = None
        with self._lock:
            self._data_staleness = value

    # ------------------------------------------------------------------
    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            latencies = list(self._latency_samples)
            latency_count = self._latency_count
            rejects = dict(self._order_rejects)
            ws_reconnects = self._ws_reconnects
            staleness = self._data_staleness

        latencies_sorted = sorted(latencies)
        p50 = _percentile(latencies_sorted, 0.5) if latencies_sorted else None
        p95 = _percentile(latencies_sorted, 0.95) if latencies_sorted else None
        latest = latencies[-1] if latencies else None

        return {
            "order_latency_ms": {
                "p50": p50,
                "p95": p95,
                "count": latency_count,
                "latest": latest,
            },
            "order_rejects_total": {
                "total": sum(rejects.values()),
                "by_code": rejects,
            },
            "ws_reconnects_total": ws_reconnects,
            "data_staleness_sec": staleness,
        }


metrics = TelemetryMetrics()


@contextmanager
def record_order_latency() -> Iterator[None]:
    """Context manager to time synchronous broker calls."""

    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        metrics.observe_order_latency(elapsed_ms)


@asynccontextmanager
async def record_order_latency_async() -> AsyncIterator[None]:
    """Async context manager to time awaited broker calls."""

    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        metrics.observe_order_latency(elapsed_ms)
