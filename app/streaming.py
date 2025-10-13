from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Dict, Iterable

try:  # pragma: no cover - optional dependency
    from alpaca.data.enums import DataFeed
except Exception:  # pragma: no cover - testing fallback
    class _StubFeed:
        def __init__(self, name: str) -> None:
            self._name = name.upper()

        def __str__(self) -> str:
            return f"DataFeed.{self._name}"

    class _StubDataFeed:
        SIP = _StubFeed("SIP")
        IEX = _StubFeed("IEX")

    DataFeed = _StubDataFeed()  # type: ignore[assignment]

try:  # pragma: no cover - optional dependency
    from alpaca.data.live import StockDataStream
except Exception:  # pragma: no cover - testing fallback
    class StockDataStream:  # type: ignore[override]
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise ImportError(
                "alpaca-py streaming components unavailable; install alpaca-py to stream"
            )

from app.data.entitlement import select_feed
from core.kill_switch import is_active


def _staleness_threshold() -> float:
    try:
        return float(os.getenv("DATA_STALENESS_SEC", "5"))
    except Exception:
        return 5.0


def _select_feed_with_probe() -> DataFeed:
    strict = os.getenv("STRICT_SIP", "").lower() == "true"
    feed_name = select_feed(strict_sip=strict)
    feed_key = (feed_name or "sip").strip().lower()

    if feed_key == "sip":
        return DataFeed.SIP
    if feed_key == "iex":
        if strict:
            raise RuntimeError("STRICT_SIP=true but SIP entitlement not available.")
        return DataFeed.IEX

    # Allow custom feeds; only reject when STRICT_SIP forces SIP usage.
    if strict:
        raise RuntimeError("STRICT_SIP=true but SIP entitlement not available.")

    return getattr(DataFeed, feed_key.upper(), DataFeed.IEX)


def _credentials():
    """Return Alpaca credentials supporting legacy and new env var names."""

    key = (
        os.getenv("ALPACA_API_KEY")
        or os.getenv("ALPACA_API_KEY_ID")
        or os.getenv("APCA_API_KEY_ID")
    )
    secret = (
        os.getenv("ALPACA_API_SECRET")
        or os.getenv("ALPACA_API_SECRET_KEY")
        or os.getenv("APCA_API_SECRET_KEY")
    )
    return key, secret


async def stream_bars(symbols: Iterable[str], minutes: int | None = None, on_health=None):
    key, secret = _credentials()
    if not key or not secret:
        raise RuntimeError(
            "Missing Alpaca credentials. Ensure ALPACA_API_KEY/ALPACA_API_SECRET or "
            "APCA_API_KEY_ID/APCA_API_SECRET_KEY are set."
        )
    feed = _select_feed_with_probe()
    stream = StockDataStream(key, secret, feed=feed)
    last_update: Dict[str, float] = {}
    stale_thr = _staleness_threshold()
    state = {
        "feed": str(feed).split(".")[-1],
        "stale": set(),
        "ok": set(s.upper() for s in symbols),
    }

    def publish():
        if on_health:
            on_health(
                {
                    "feed": state["feed"],
                    "ok": sorted(state["ok"]),
                    "stale": sorted(state["stale"]),
                    "threshold_s": stale_thr,
                }
            )

    async def on_bar(bar):
        try:
            sym = bar.symbol.upper()
            evt_dt = getattr(bar, "timestamp", None) or datetime.now(tz=timezone.utc)
            if isinstance(evt_dt, str):
                evt_dt = datetime.fromisoformat(evt_dt.replace("Z", "+00:00")).astimezone(
                    timezone.utc
                )
            ing = datetime.now(tz=timezone.utc)
            latency = (ing - evt_dt).total_seconds()
            last_update[sym] = time.time()
            if sym in state["stale"]:
                state["stale"].discard(sym)
                state["ok"].add(sym)
                publish()
            print(f"BAR {sym} close={bar.close} latency={latency:.3f}s feed={state['feed']}")
        except Exception as exc:
            print(f"[stream] error processing bar: {exc}")

    stream.subscribe_bars(on_bar, *symbols)
    publish()

    async def watchdog():
        while True:
            if is_active():
                print("[health] kill switch engaged; stopping stream.")
                await stream.stop()
                break
            now = time.time()
            changed = False
            for sym in list(state["ok"] | state["stale"]):
                if now - last_update.get(sym, 0) > stale_thr:
                    if sym not in state["stale"]:
                        state["stale"].add(sym)
                        state["ok"].discard(sym)
                        changed = True
            if changed:
                stale_list = sorted(state["stale"])
                ok_list = sorted(state["ok"])
                print(f"[health] stale={stale_list} ok={ok_list} thr={stale_thr}s")
                publish()
            await asyncio.sleep(1.0)

    async def limiter():
        if minutes is None:
            return
        await asyncio.sleep(minutes * 60.0)
        await stream.stop()

    await asyncio.gather(stream.run(), watchdog(), limiter())
