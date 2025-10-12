from __future__ import annotations

import asyncio
import os
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Iterable, List

from dotenv import load_dotenv

from alpaca.data.live import StockDataStream

from app.alpaca_client import build_trading_client
from app.execution.alpaca_orders import build_limit_order, build_market_order, submit_order_sync
from app.streaming import _select_feed_with_probe, _staleness_threshold

load_dotenv()

_STATE: Dict[str, object] = {
    "thread": None,
    "loop": None,
    "stream": None,
    "stop_event": None,
    "symbols": [],
    "latest": {},
    "latency": defaultdict(list),
    "feed": "",
    "stale": set(),
    "last_update": {},
    "staleness": _staleness_threshold(),
}
_LOCK = threading.Lock()
_MAX_LATENCY_SAMPLES = 200


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _update_state(symbol: str, bar) -> None:
    event_ts = getattr(bar, "timestamp", None) or _now_utc()
    if isinstance(event_ts, str):
        event_ts = datetime.fromisoformat(event_ts.replace("Z", "+00:00")).astimezone(timezone.utc)
    ingestion = _now_utc()
    latency = max((ingestion - event_ts).total_seconds(), 0.0)
    with _LOCK:
        _STATE["latest"][symbol] = {
            "symbol": symbol,
            "close": getattr(bar, "close", None),
            "timestamp": event_ts,
            "latency": latency,
            "ingested_at": ingestion,
        }
        lat_samples: List[float] = _STATE["latency"][symbol]
        lat_samples.append(latency)
        if len(lat_samples) > _MAX_LATENCY_SAMPLES:
            del lat_samples[:-_MAX_LATENCY_SAMPLES]
        _STATE["last_update"][symbol] = time.time()
        if symbol in _STATE["stale"]:
            _STATE["stale"].discard(symbol)


def _run_stream(symbols: Iterable[str]) -> None:
    load_dotenv()
    api_key = os.getenv("ALPACA_API_KEY")
    api_secret = os.getenv("ALPACA_API_SECRET")
    if not api_key or not api_secret:
        return
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    feed = _select_feed_with_probe()
    stream = StockDataStream(api_key, api_secret, feed=feed)
    stop_event = threading.Event()
    with _LOCK:
        _STATE.update(
            {
                "loop": loop,
                "stream": stream,
                "stop_event": stop_event,
                "feed": str(feed).split(".")[-1],
                "symbols": [s.upper() for s in symbols],
                "stale": set(s.upper() for s in symbols),
            }
        )
    stale_threshold = _STATE["staleness"]

    async def on_bar(bar):
        try:
            symbol = bar.symbol.upper()
            _update_state(symbol, bar)
            print(
                f"[ui-stream] BAR {symbol} close={getattr(bar, 'close', '?')} feed={_STATE['feed']}"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[ui-stream] error processing bar: {exc}")

    if _STATE["symbols"]:
        stream.subscribe_bars(on_bar, *_STATE["symbols"])

    async def watchdog():
        while not stop_event.is_set():
            now = time.time()
            stale_changes = False
            with _LOCK:
                symbols_upper = list(_STATE["symbols"])
                for sym in symbols_upper:
                    last = _STATE["last_update"].get(sym, 0.0)
                    if now - last > stale_threshold:
                        if sym not in _STATE["stale"]:
                            _STATE["stale"].add(sym)
                            stale_changes = True
                    else:
                        if sym in _STATE["stale"]:
                            _STATE["stale"].discard(sym)
                            stale_changes = True
            if stale_changes:
                print(
                    f"[ui-stream] stale={sorted(_STATE['stale'])} ok={sorted(set(symbols_upper) - set(_STATE['stale']))}"
                )
            await asyncio.sleep(1.0)
        await stream.stop()

    async def runner():
        await stream.run()

    try:
        loop.run_until_complete(asyncio.gather(runner(), watchdog()))
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        finally:
            loop.close()
        with _LOCK:
            _STATE.update({"loop": None, "stream": None, "stop_event": None, "thread": None})


def start_stream(symbols: Iterable[str]) -> None:
    stop_stream()
    symbols_list = [s.strip().upper() for s in symbols if s.strip()]
    if not symbols_list:
        return
    thread = threading.Thread(target=_run_stream, args=(symbols_list,), daemon=True)
    with _LOCK:
        _STATE.update(
            {"thread": thread, "symbols": symbols_list, "staleness": _staleness_threshold()}
        )
        _STATE["stale"] = set(symbols_list)
        _STATE["latest"] = {}
        _STATE["last_update"] = {}
        latency = _STATE.get("latency")
        if hasattr(latency, "clear"):
            latency.clear()
    thread.start()


def stop_stream() -> None:
    with _LOCK:
        thread = _STATE.get("thread")
        loop = _STATE.get("loop")
        stream = _STATE.get("stream")
        stop_event = _STATE.get("stop_event")
    if stop_event is not None:
        stop_event.set()
    if loop and stream:
        try:
            future = asyncio.run_coroutine_threadsafe(stream.stop(), loop)
            future.result(timeout=5)
        except Exception:
            pass
    if thread and isinstance(thread, threading.Thread) and thread.is_alive():
        thread.join(timeout=5)
    with _LOCK:
        _STATE.update({"thread": None, "loop": None, "stream": None, "stop_event": None})
        _STATE["stale"] = set()
        _STATE["symbols"] = []
        _STATE["latest"] = {}
        _STATE["last_update"] = {}
        latency = _STATE.get("latency")
        if hasattr(latency, "clear"):
            latency.clear()


def get_latest_bars() -> List[Dict[str, object]]:
    now = _now_utc()
    with _LOCK:
        values = list(_STATE["latest"].values())
    enriched: List[Dict[str, object]] = []
    for item in values:
        timestamp = item.get("timestamp")
        age = None
        if isinstance(timestamp, datetime):
            age = max((now - timestamp).total_seconds(), 0.0)
        enriched.append(
            {
                "symbol": item.get("symbol"),
                "close": item.get("close"),
                "timestamp": timestamp,
                "latency": item.get("latency"),
                "age": age,
            }
        )
    return sorted(enriched, key=lambda row: row["symbol"] or "")


def get_latency_samples() -> Dict[str, List[float]]:
    with _LOCK:
        return {sym: list(samples) for sym, samples in _STATE["latency"].items()}


def get_stream_health() -> Dict[str, object]:
    with _LOCK:
        symbols = list(_STATE["symbols"])
        stale = sorted(_STATE["stale"])
        ok = sorted(sym for sym in symbols if sym not in _STATE["stale"])
        feed = _STATE.get("feed", "")
        threshold = _STATE.get("staleness", 5.0)
    return {"feed": feed, "ok": ok, "stale": stale, "threshold_s": threshold}


def get_account_summary() -> Dict[str, object]:
    try:
        client = build_trading_client()
        account = client.get_account()
        return {
            "status": getattr(account, "status", "unknown"),
            "equity": getattr(account, "portfolio_value", None),
            "cash": getattr(account, "cash", None),
            "multiplier": getattr(account, "multiplier", None),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def place_test_order(symbol: str, qty: int, order_type: str, limit_price: float | None = None):
    if os.getenv("LIVE_TRADING", "").lower() == "true":
        raise RuntimeError("Test orders disabled in LIVE mode.")
    client = build_trading_client()
    if order_type.lower() == "market":
        req = build_market_order(symbol, qty, "buy", "DAY")
    elif order_type.lower() == "limit":
        if limit_price is None:
            raise ValueError("limit orders require limit_price")
        req = build_limit_order(symbol, qty, "buy", float(limit_price), "DAY")
    else:
        raise ValueError("order_type must be 'market' or 'limit'")
    order = submit_order_sync(client, req)
    return {
        "id": getattr(order, "id", None),
        "status": getattr(order, "status", None),
        "symbol": getattr(order, "symbol", symbol),
    }
