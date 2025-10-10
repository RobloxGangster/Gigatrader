from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Dict, Iterable

from alpaca.data.enums import DataFeed
from alpaca.data.live import StockDataStream

from app.data.entitlement import sip_entitled

def _staleness_threshold() -> float:
    try:
        return float(os.getenv("DATA_STALENESS_SEC", "5"))
    except Exception:
        return 5.0


def _select_feed_with_probe() -> DataFeed:
    strict = os.getenv("STRICT_SIP", "").lower() == "true"
    if sip_entitled():
        return DataFeed.SIP
    if strict:
        raise RuntimeError("STRICT_SIP=true but SIP entitlement not available.")
    return DataFeed.IEX



def _credentials():
    return os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_API_SECRET")


async def stream_bars(
    symbols: Iterable[str], minutes: int | None = None, on_health=None
):
    key, secret = _credentials()
    if not key or not secret:
        raise RuntimeError("Missing ALPACA_API_KEY/ALPACA_API_SECRET.")
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
            print(
                f"BAR {sym} close={bar.close} latency={latency:.3f}s feed={state['feed']}"
            )
        except Exception as exc:
            print(f"[stream] error processing bar: {exc}")

    stream.subscribe_bars(on_bar, *symbols)
    publish()

    async def watchdog():
        while True:
            now = time.time()
            changed = False
            for sym in list(state["ok"] | state["stale"]):
                if now - last_update.get(sym, 0) > stale_thr:
                    if sym not in state["stale"]:
                        state["stale"].add(sym)
                        state["ok"].discard(sym)
                        changed = True
            if changed:
                print(
                    f"[health] stale={sorted(state['stale'])} ok={sorted(state['ok'])} thr={stale_thr}s"
                )
                publish()
            await asyncio.sleep(1.0)

    async def limiter():
        if minutes is None:
            return
        await asyncio.sleep(minutes * 60.0)
        await stream.stop()

    await asyncio.gather(stream.run(), watchdog(), limiter())
