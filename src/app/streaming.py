"""Streaming helpers for Alpaca market data."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
from contextlib import suppress
from typing import Callable, Optional, Sequence

from core.config import get_alpaca_settings
from core.utils import ensure_paper_mode

from app.data.quality import FeedHealth, get_data_staleness_seconds, resolve_data_feed_name

LOGGER = logging.getLogger(__name__)


class FeedMonitor:
    """Coordinate a StockDataStream session while tracking feed health."""

    def __init__(
        self,
        symbols: Sequence[str],
        feed_health: FeedHealth,
        *,
        staleness_sec: Optional[int] = None,
        on_bar: Optional[Callable[[str, object], None]] = None,
    ) -> None:
        self._symbols = [symbol.upper() for symbol in symbols]
        self._feed_health = feed_health
        self._on_bar = on_bar
        self._staleness_sec = staleness_sec or get_data_staleness_seconds()
        self._stop_event = asyncio.Event()
        self._watchdog_task: Optional[asyncio.Task] = None
        self._stream_task: Optional[asyncio.Task] = None
        self._stream = None

    async def run(self, duration_seconds: float) -> None:
        """Run the bar stream for ``duration_seconds`` and evaluate health."""

        if not self._symbols:
            raise ValueError("At least one symbol is required")
        stream = self._build_stream()
        self._stream = stream
        for symbol in self._symbols:
            stream.subscribe_bars(self._handle_bar, symbol)
        self._stream_task = asyncio.create_task(stream._run_forever())  # pylint: disable=protected-access
        self._watchdog_task = asyncio.create_task(self._watchdog())
        try:
            await asyncio.sleep(duration_seconds)
        finally:
            await self._shutdown()

    async def _handle_bar(self, bar: object) -> None:
        symbol = _extract_symbol(bar)
        if not symbol:
            return
        event_ts = _extract_event_timestamp(bar)
        ingest_ts = dt.datetime.now(dt.timezone.utc)
        if event_ts is None:
            event_ts = ingest_ts
        self._feed_health.note_event(symbol, event_ts, ingest_ts)
        self._feed_health.update_last_price(symbol, _extract_event_price(bar))
        if self._on_bar:
            try:
                self._on_bar(symbol, bar)
            except Exception:  # noqa: BLE001
                LOGGER.exception("on_bar callback failed", exc_info=True)

    async def _watchdog(self) -> None:
        """Periodic staleness evaluation."""

        while not self._stop_event.is_set():
            await asyncio.sleep(1)
            now = dt.datetime.now(dt.timezone.utc)
            for symbol in self._symbols:
                self._feed_health.is_stale(symbol, now, self._staleness_sec)

    async def _shutdown(self) -> None:
        self._stop_event.set()
        if self._watchdog_task:
            self._watchdog_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._watchdog_task
        if self._stream:
            self._stream.stop()
        if self._stream_task:
            self._stream_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._stream_task

    def _build_stream(self):
        settings = get_alpaca_settings()
        key = settings.key_id or os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
        secret = settings.secret_key or os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")
        if not key or not secret:
            raise RuntimeError("Alpaca API credentials are required for streaming")
        paper = ensure_paper_mode(default=True) != "live"
        try:
            from alpaca.data.enums import DataFeed  # type: ignore
            from alpaca.data.live import StockDataStream  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover - guard path
            raise RuntimeError("alpaca-py is required for streaming") from exc

        feed_name = resolve_data_feed_name()
        data_feed = DataFeed[feed_name.upper()]
        return StockDataStream(key, secret, paper=paper, feed=data_feed)


async def monitor_feed(
    symbols: Sequence[str],
    duration_seconds: float,
    *,
    feed_health: Optional[FeedHealth] = None,
    staleness_sec: Optional[int] = None,
    on_bar: Optional[Callable[[str, object], None]] = None,
) -> FeedHealth:
    """Run a streaming session and return the populated :class:`FeedHealth`."""

    health = feed_health or FeedHealth()
    monitor = FeedMonitor(symbols, health, staleness_sec=staleness_sec, on_bar=on_bar)
    await monitor.run(duration_seconds)
    return health


def _extract_symbol(bar: object) -> Optional[str]:
    if isinstance(bar, dict):
        symbol = bar.get("symbol") or bar.get("S")
        return str(symbol) if symbol else None
    for attr in ("symbol", "S"):
        if hasattr(bar, attr):
            value = getattr(bar, attr)
            return str(value) if value else None
    return None


def _extract_event_timestamp(bar: object) -> Optional[dt.datetime]:
    if isinstance(bar, dict):
        candidate = bar.get("timestamp") or bar.get("t") or bar.get("time")
    else:
        candidate = None
        for attr in ("timestamp", "t", "time"):
            if hasattr(bar, attr):
                candidate = getattr(bar, attr)
                break
    if candidate is None:
        return None
    return _coerce_datetime(candidate)


def _extract_event_price(bar: object) -> Optional[float]:
    if isinstance(bar, dict):
        for key in ("close", "c", "price"):
            value = bar.get(key)
            if value is not None:
                return float(value)
    for attr in ("close", "c", "price"):
        if hasattr(bar, attr):
            value = getattr(bar, attr)
            if value is not None:
                return float(value)
    return None


def _coerce_datetime(value: object) -> Optional[dt.datetime]:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc)
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(float(value), tz=dt.timezone.utc)
    if isinstance(value, str):
        try:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
        except ValueError:
            return None
    return None
