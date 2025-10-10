from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from collections import deque
import inspect
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Deque, Dict, Iterable, List, Optional

if TYPE_CHECKING:  # pragma: no cover - type checking only
    from app.data.quality import FeedHealth

from app.data.entitlement import sip_entitled

try:  # pragma: no cover - allow operation without alpaca-py
    from alpaca.common.exceptions import APIError
except ModuleNotFoundError:  # pragma: no cover - testing environment fallback
    class APIError(Exception):  # type: ignore
        """Fallback APIError when alpaca-py is unavailable."""

try:  # pragma: no cover - allow import when alpaca-py missing
    from alpaca.data.enums import DataFeed
except ModuleNotFoundError:  # pragma: no cover - provide lightweight stand-in
    from enum import Enum

    class DataFeed(Enum):  # type: ignore
        SIP = "sip"
        IEX = "iex"


LOGGER = logging.getLogger(__name__)


def _get_credentials() -> tuple[Optional[str], Optional[str]]:
    key = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
    secret = os.getenv("ALPACA_API_SECRET") or os.getenv("APCA_API_SECRET_KEY")
    if not key:
        key = os.getenv("ALPACA_KEY_ID")
    if not secret:
        secret = os.getenv("ALPACA_SECRET_KEY")
    return key, secret


def _staleness_threshold() -> float:
    try:
        return float(os.getenv("DATA_STALENESS_SEC", "5"))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return 5.0


def _select_feed_with_probe() -> DataFeed:
    strict = os.getenv("STRICT_SIP", "").lower() == "true"
    entitled = False
    try:
        entitled = sip_entitled()
    except Exception as exc:  # noqa: BLE001 - defensive; should rarely occur
        LOGGER.warning("SIP entitlement probe failed: %s", exc)
    if entitled:
        LOGGER.info("Using SIP feed after entitlement probe succeeded")
        return DataFeed.SIP
    if strict:
        raise RuntimeError("STRICT_SIP=true but SIP entitlement not available.")
    LOGGER.warning("Falling back to IEX feed — SIP entitlement missing or probe failed")
    return DataFeed.IEX


def _compute_percentile(values: List[float], percentile: float) -> Optional[float]:
    if not values:
        return None
    sorted_vals = sorted(values)
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    rank = (len(sorted_vals) - 1) * percentile
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return float(sorted_vals[int(rank)])
    lower_val = sorted_vals[lower]
    upper_val = sorted_vals[upper]
    return float(lower_val + (upper_val - lower_val) * (rank - lower))


def _latency_snapshot(latency_history: Dict[str, Deque[float]], latest_latency: Dict[str, float]) -> Dict[str, Dict[str, Optional[float]]]:
    snapshot: Dict[str, Dict[str, Optional[float]]] = {}
    for symbol, history in latency_history.items():
        values = list(history)
        snapshot[symbol] = {
            "p50": _compute_percentile(values, 0.50),
            "p95": _compute_percentile(values, 0.95),
            "last": latest_latency.get(symbol),
        }
    return snapshot


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return _now()
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    return _now()


def _build_stream(feed: DataFeed):
    try:
        from alpaca.data.live import StockDataStream
    except ModuleNotFoundError as exc:  # pragma: no cover - triggered in CI without alpaca-py
        raise RuntimeError("alpaca-py is required for streaming") from exc

    key, secret = _get_credentials()
    if not key or not secret:
        raise RuntimeError("Missing ALPACA_API_KEY/SECRET for streaming")
    return StockDataStream(key, secret, feed=feed)


async def stream_bars(
    symbols: Iterable[str],
    minutes: Optional[float] = None,
    on_health: Optional[Callable[[Dict[str, Any]], None]] = None,
    on_bar: Optional[Callable[[str, Any], Any]] = None,
) -> None:
    symbol_list = [symbol.strip().upper() for symbol in symbols if symbol]
    if not symbol_list:
        raise ValueError("At least one symbol is required for streaming")

    feed = _select_feed_with_probe()
    stream = _build_stream(feed)

    last_update: Dict[str, float] = {symbol: time.time() for symbol in symbol_list}
    latency_history: Dict[str, Deque[float]] = {symbol: deque(maxlen=200) for symbol in symbol_list}
    latest_latency: Dict[str, float] = {symbol: 0.0 for symbol in symbol_list}
    state = {
        "feed": feed,
        "ok": set(symbol_list),
        "stale": set(),
        "threshold": _staleness_threshold(),
    }

    def publish(state_changed: bool = False) -> None:
        if on_health is None:
            return
        payload = {
            "feed": state["feed"].name if hasattr(state["feed"], "name") else str(state["feed"]),
            "ok": sorted(state["ok"]),
            "stale": sorted(state["stale"]),
            "threshold_s": state["threshold"],
            "latency": _latency_snapshot(latency_history, latest_latency),
        }
        if state_changed:
            LOGGER.info("Health update: %s", payload)
        on_health(payload)

    async def handle_bar(bar: Any) -> None:
        try:
            sym = getattr(bar, "symbol", None) or getattr(bar, "S", None)
            if sym is None and isinstance(bar, dict):
                sym = bar.get("symbol") or bar.get("S")
            if sym is None:
                return
            sym = str(sym).upper()
            event_time = getattr(bar, "timestamp", None)
            if event_time is None and isinstance(bar, dict):
                event_time = bar.get("timestamp") or bar.get("t")
            event_dt = _as_datetime(event_time)
            ingest_dt = _now()
            latency = max(0.0, (ingest_dt - event_dt).total_seconds())
            latest_latency[sym] = latency
            latency_history.setdefault(sym, deque(maxlen=200)).append(latency)
            last_update[sym] = time.time()
            if sym in state["stale"]:
                state["stale"].discard(sym)
                state["ok"].add(sym)
                publish(state_changed=True)
            LOGGER.info(
                "BAR %s close=%s latency=%.3fs feed=%s",
                sym,
                getattr(bar, "close", getattr(bar, "c", None)) if not isinstance(bar, dict) else bar.get("close"),
                latency,
                state["feed"],
            )
            if on_bar is not None:
                try:
                    result = on_bar(sym, bar)
                    if inspect.isawaitable(result):
                        await result
                except Exception as callback_exc:  # noqa: BLE001 - keep stream running
                    LOGGER.warning("on_bar callback failed for %s: %s", sym, callback_exc)
            publish()
        except Exception as exc:  # noqa: BLE001 - guard to keep stream alive
            LOGGER.exception("Error processing bar: %s", exc)

    stream.subscribe_bars(handle_bar, *symbol_list)
    publish(state_changed=True)

    stop_event = asyncio.Event()

    async def watchdog() -> None:
        try:
            while not stop_event.is_set():
                await asyncio.sleep(1.0)
                now = time.time()
                changed = False
                for sym in symbol_list:
                    last = last_update.get(sym, 0.0)
                    if now - last > state["threshold"]:
                        if sym not in state["stale"]:
                            state["stale"].add(sym)
                            state["ok"].discard(sym)
                            changed = True
                if changed:
                    LOGGER.warning("Symbols marked stale: %s", sorted(state["stale"]))
                    publish(state_changed=True)
        finally:
            publish()

    async def limiter() -> None:
        if minutes is None:
            return
        await asyncio.sleep(minutes * 60.0)
        await stream.stop()

    async def runner() -> None:
        try:
            await stream.run()
        except APIError as exc:
            LOGGER.error("Stream terminated due to API error: %s", exc)
            raise
        finally:
            stop_event.set()

    tasks = [
        asyncio.create_task(runner()),
        asyncio.create_task(watchdog()),
    ]
    if minutes is not None:
        tasks.append(asyncio.create_task(limiter()))

    try:
        await asyncio.gather(*tasks)
    finally:
        stop_event.set()
        await stream.stop()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        publish()


def _extract_price(bar: Any) -> Optional[float]:
    if isinstance(bar, dict):
        for key in ("close", "c", "price"):
            value = bar.get(key)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None
        return None
    for attr in ("close", "c", "price"):
        if hasattr(bar, attr):
            value = getattr(bar, attr)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None
    return None


async def monitor_feed(
    symbols: Iterable[str],
    duration_seconds: float,
    *,
    feed_health: Optional["FeedHealth"] = None,
    staleness_sec: Optional[int] = None,
    on_bar: Optional[Callable[[str, Any], Any]] = None,
) -> Optional["FeedHealth"]:
    if feed_health is None:
        try:
            from app.data.quality import FeedHealth as FeedHealthCls
        except ImportError as exc:  # pragma: no cover - defensive
            raise RuntimeError("FeedHealth class unavailable") from exc
        feed_health = FeedHealthCls()

    threshold = staleness_sec if staleness_sec is not None else int(_staleness_threshold())

    def _on_bar(symbol: str, bar: Any) -> None:
        event_time = getattr(bar, "timestamp", None)
        if event_time is None and isinstance(bar, dict):
            event_time = bar.get("timestamp") or bar.get("t")
        event_dt = _as_datetime(event_time)
        ingest_dt = _now()
        feed_health.note_event(symbol, event_dt, ingest_dt)
        feed_health.update_last_price(symbol, _extract_price(bar))
        if on_bar is not None:
            on_bar(symbol, bar)

    def _on_health(update: Dict[str, Any]) -> None:
        now = _now()
        for sym in update.get("stale", []):
            feed_health.is_stale(sym, now, threshold)

    minutes = max(duration_seconds / 60.0, 0.0)
    await stream_bars(symbols, minutes=minutes, on_health=_on_health, on_bar=_on_bar)
    return feed_health


__all__ = ["stream_bars", "_select_feed_with_probe", "monitor_feed"]
