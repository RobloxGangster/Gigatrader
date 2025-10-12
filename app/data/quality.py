"""Market data quality utilities and health tracking."""

from __future__ import annotations

import datetime as dt
import logging
import math
import os
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, Dict, List, Optional

from core.config import get_alpaca_settings

LOGGER = logging.getLogger(__name__)

# Default monitoring parameters
_DEFAULT_STALENESS_SECONDS = 5
_SNAPSHOT_SKEW_THRESHOLD = 2.0  # seconds
_MAX_LATENCY_SAMPLES = 500
_REGULAR_START_UTC = dt.time(hour=13, minute=30)  # 09:30 ET
_REGULAR_END_UTC = dt.time(hour=20, minute=0)  # 16:00 ET


@dataclass(slots=True)
class SymbolHealth:
    """Mutable state tracked for an individual symbol."""

    last_event_ts: Optional[dt.datetime] = None
    last_ingest_ts: Optional[dt.datetime] = None
    latencies: Deque[float] = field(default_factory=lambda: deque(maxlen=_MAX_LATENCY_SAMPLES))
    status: str = "STALE"
    last_transition: Optional[dt.datetime] = None
    last_price: Optional[float] = None


class FeedHealth:
    """Track feed health metrics and expose diagnostic helpers."""

    def __init__(
        self,
        *,
        historical_client: Optional[object] = None,
        on_state_change: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self._symbols: Dict[str, SymbolHealth] = {}
        self._historical_client = historical_client
        self._on_state_change = on_state_change
        self._market_open = True
        self._feed_name = resolve_data_feed_name()

    # ------------------------------------------------------------------
    # Symbol lifecycle helpers
    def _ensure_symbol(self, symbol: str) -> SymbolHealth:
        symbol = symbol.upper()
        if symbol not in self._symbols:
            self._symbols[symbol] = SymbolHealth()
        return self._symbols[symbol]

    def set_market_open(self, is_open: bool) -> None:
        """Record whether the market is currently open."""

        self._market_open = bool(is_open)

    # ------------------------------------------------------------------
    # Event ingestion & staleness
    def note_event(self, symbol: str, event_ts: dt.datetime, ingest_ts: dt.datetime) -> None:
        """Record the arrival of a streamed bar or trade event."""

        stats = self._ensure_symbol(symbol)
        event_ts = _ensure_utc(event_ts)
        ingest_ts = _ensure_utc(ingest_ts)

        stats.last_event_ts = event_ts
        stats.last_ingest_ts = ingest_ts
        latency = (ingest_ts - event_ts).total_seconds()
        if latency >= 0:
            stats.latencies.append(latency)
        self._set_status(symbol, "OK", ingest_ts)

    def update_last_price(self, symbol: str, price: Optional[float]) -> None:
        """Persist the latest observed stream price for later comparisons."""

        if price is None:
            return
        stats = self._ensure_symbol(symbol)
        stats.last_price = float(price)

    def is_stale(self, symbol: str, now: dt.datetime, staleness_sec: int) -> bool:
        """Return ``True`` when the feed is stale for ``symbol``."""

        stats = self._symbols.get(symbol.upper())
        if stats is None:
            return True
        if not self._market_open:
            return False
        if stats.last_event_ts is None:
            return True
        now = _ensure_utc(now)
        delta = (now - stats.last_event_ts).total_seconds()
        if delta > staleness_sec:
            self._set_status(symbol, "STALE", now)
            return True
        return False

    # ------------------------------------------------------------------
    # Summaries
    def get_status(self, symbol: str) -> str:
        """Return the current flag for ``symbol``."""

        stats = self._symbols.get(symbol.upper())
        return stats.status if stats else "UNKNOWN"

    def latency_summary(self, symbol: str) -> dict:
        """Return latency percentiles for ``symbol``."""

        stats = self._symbols.get(symbol.upper())
        if stats is None or not stats.latencies:
            return {"p50": None, "p95": None}
        values = sorted(stats.latencies)
        p50 = _percentile(values, 0.5)
        p95 = _percentile(values, 0.95)
        return {"p50": p50, "p95": p95}

    def snapshot(self) -> List[dict]:
        """Return a summary of symbol states for UI/CLI rendering."""

        report: List[dict] = []
        for symbol in sorted(self._symbols):
            stats = self._symbols[symbol]
            report.append(
                {
                    "symbol": symbol,
                    "status": stats.status,
                    "last_event_ts": stats.last_event_ts,
                    "last_ingest_ts": stats.last_ingest_ts,
                    "latency": self.latency_summary(symbol),
                    "last_price": stats.last_price,
                }
            )
        return report

    # ------------------------------------------------------------------
    # Cross checks
    def crosscheck_snapshot(self, symbols: List[str]) -> List[dict]:
        """Compare latest snapshots against stream state and return mismatches."""

        if not symbols:
            return []
        client = self._ensure_historical_client()
        try:
            from alpaca.data.requests import StockSnapshotRequest  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover - guard path
            raise RuntimeError("alpaca-py is required for snapshot cross-checks") from exc

        request = StockSnapshotRequest(
            symbol_or_symbols=symbols, feed=_ensure_data_feed_enum(self._feed_name)
        )
        snapshots = client.get_stock_snapshots(request)
        mismatches: List[dict] = []
        for symbol in symbols:
            stats = self._symbols.get(symbol.upper())
            stream_ts = stats.last_event_ts if stats else None
            stream_price = stats.last_price if stats else None
            snapshot = snapshots.get(symbol)
            snapshot_ts = _extract_snapshot_timestamp(snapshot)
            snapshot_price = _extract_snapshot_price(snapshot)
            if not stream_ts or not snapshot_ts:
                continue
            delta = abs((snapshot_ts - stream_ts).total_seconds())
            price_delta = None
            if snapshot_price is not None and stream_price is not None:
                price_delta = snapshot_price - stream_price
            if delta > _SNAPSHOT_SKEW_THRESHOLD or (
                price_delta is not None and abs(price_delta) > 0
            ):
                mismatches.append(
                    {
                        "symbol": symbol,
                        "delta_seconds": delta,
                        "stream_timestamp": stream_ts,
                        "snapshot_timestamp": snapshot_ts,
                        "stream_price": stream_price,
                        "snapshot_price": snapshot_price,
                        "price_delta": price_delta,
                    }
                )
        return mismatches

    def check_bar_continuity(
        self,
        symbols: List[str],
        start: dt.datetime,
        end: dt.datetime,
    ) -> List[dict]:
        """Return detected gaps in 1-minute bars during regular market hours."""

        if not symbols:
            return []
        client = self._ensure_historical_client()
        try:
            from alpaca.data.requests import StockBarsRequest  # type: ignore
            from alpaca.data.timeframe import TimeFrame  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover - guard path
            raise RuntimeError("alpaca-py is required for bar continuity checks") from exc

        start = _ensure_utc(start)
        end = _ensure_utc(end)
        request = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame.Minute,
            start=start,
            end=end,
            feed=_ensure_data_feed_enum(self._feed_name),
        )
        response = client.get_stock_bars(request)
        symbol_bars = _normalise_bar_response(response)
        gaps: List[dict] = []
        for symbol in symbols:
            bars = symbol_bars.get(symbol, [])
            if not bars:
                continue
            bars.sort(key=_extract_bar_timestamp)
            previous_ts: Optional[dt.datetime] = None
            for bar in bars:
                current_ts = _extract_bar_timestamp(bar)
                if previous_ts is None:
                    previous_ts = current_ts
                    continue
                delta = (current_ts - previous_ts).total_seconds()
                if _is_regular_session(previous_ts) and _is_regular_session(current_ts):
                    missing = int(delta // 60) - 1
                    if missing > 0:
                        gaps.append(
                            {
                                "symbol": symbol,
                                "start": previous_ts,
                                "end": current_ts,
                                "missing_minutes": missing,
                            }
                        )
                previous_ts = current_ts
        return gaps

    # ------------------------------------------------------------------
    # Internal helpers
    def _set_status(self, symbol: str, status: str, timestamp: dt.datetime) -> None:
        stats = self._ensure_symbol(symbol)
        if stats.status != status:
            stats.status = status
            stats.last_transition = timestamp
            if self._on_state_change:
                try:
                    self._on_state_change(symbol.upper(), status)
                except Exception:  # noqa: BLE001
                    LOGGER.exception("FeedHealth state change callback failed")

    def _ensure_historical_client(self):
        if self._historical_client is not None:
            return self._historical_client
        try:
            from alpaca.data.historical import StockHistoricalDataClient  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover - guard path
            raise RuntimeError("alpaca-py is required for historical data") from exc

        settings = get_alpaca_settings()
        key = settings.key_id or None
        secret = settings.secret_key or None
        self._historical_client = StockHistoricalDataClient(api_key=key, secret_key=secret)
        return self._historical_client


# ----------------------------------------------------------------------
# Environment helpers


def resolve_data_feed_name() -> str:
    """Return the configured Alpaca data feed (``iex`` default)."""

    feed = os.getenv("ALPACA_DATA_FEED", "").strip().upper()
    return "sip" if feed == "SIP" else "iex"


def get_data_staleness_seconds(default: int = _DEFAULT_STALENESS_SECONDS) -> int:
    """Return the configured staleness threshold."""

    raw = os.getenv("DATA_STALENESS_SEC")
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        LOGGER.warning("Invalid DATA_STALENESS_SEC=%s, using default %s", raw, default)
        return default
    return max(1, value)


# ----------------------------------------------------------------------
# Private helpers


def _ensure_data_feed_enum(feed_name: str):
    try:
        from alpaca.data.enums import DataFeed  # type: ignore
    except ModuleNotFoundError:  # pragma: no cover - allow tests without alpaca
        return feed_name
    return DataFeed[feed_name.upper()]


def _ensure_utc(timestamp: dt.datetime) -> dt.datetime:
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=dt.timezone.utc)
    return timestamp.astimezone(dt.timezone.utc)


def _percentile(values: List[float], quantile: float) -> float:
    if not values:
        raise ValueError("values must not be empty")
    if quantile <= 0:
        return values[0]
    if quantile >= 1:
        return values[-1]
    index = quantile * (len(values) - 1)
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return values[int(index)]
    lower_val = values[lower]
    upper_val = values[upper]
    return lower_val + (upper_val - lower_val) * (index - lower)


def _extract_snapshot_timestamp(snapshot: object) -> Optional[dt.datetime]:
    candidate = None
    if snapshot is None:
        return None
    for attr in ("latest_trade", "latest_quote", "minute_bar", "daily_bar"):
        node = getattr(snapshot, attr, None)
        if node is None and isinstance(snapshot, dict):
            node = snapshot.get(attr)
        if node is None:
            continue
        candidate = _extract_bar_timestamp(node)
        if candidate:
            break
    if candidate:
        return candidate
    if isinstance(snapshot, dict):
        raw = snapshot.get("timestamp")
        if raw:
            return _coerce_datetime(raw)
    raw = getattr(snapshot, "timestamp", None)
    return _coerce_datetime(raw)


def _extract_snapshot_price(snapshot: object) -> Optional[float]:
    if snapshot is None:
        return None
    for attr in ("latest_trade", "latest_quote", "minute_bar", "daily_bar"):
        node = getattr(snapshot, attr, None)
        if node is None and isinstance(snapshot, dict):
            node = snapshot.get(attr)
        if node is None:
            continue
        if isinstance(node, dict):
            price = node.get("price") or node.get("close") or node.get("c")
        else:
            price = (
                getattr(node, "price", None)
                or getattr(node, "close", None)
                or getattr(node, "c", None)
            )
        if price is not None:
            return float(price)
    if isinstance(snapshot, dict):
        price = snapshot.get("price") or snapshot.get("close")
        return float(price) if price is not None else None
    return None


def _coerce_datetime(value: object) -> Optional[dt.datetime]:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return _ensure_utc(value)
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(float(value), tz=dt.timezone.utc)
    if isinstance(value, str):
        try:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
                dt.timezone.utc
            )
        except ValueError:
            return None
    return None


def _extract_bar_timestamp(bar: object) -> dt.datetime:
    if isinstance(bar, dt.datetime):
        return _ensure_utc(bar)
    if isinstance(bar, dict):
        raw = bar.get("timestamp") or bar.get("t") or bar.get("time")
        if raw is None:
            raise ValueError("Bar payload missing timestamp")
        ts = _coerce_datetime(raw)
        if ts is None:
            raise ValueError("Bar timestamp is not parseable")
        return ts
    for attr in ("timestamp", "t", "time"):
        if hasattr(bar, attr):
            ts = _coerce_datetime(getattr(bar, attr))
            if ts is None:
                continue
            return ts
    raise ValueError("Unable to extract timestamp from bar payload")


def _normalise_bar_response(response: object) -> Dict[str, List[object]]:
    if isinstance(response, dict):
        return {symbol: list(bars) for symbol, bars in response.items()}
    data = getattr(response, "data", None)
    if isinstance(data, dict):
        return {symbol: list(bars) for symbol, bars in data.items()}
    return {}


def _is_regular_session(timestamp: dt.datetime) -> bool:
    timestamp = _ensure_utc(timestamp)
    market_time = timestamp.time()
    if market_time < _REGULAR_START_UTC or market_time > _REGULAR_END_UTC:
        return False
    return True
