from __future__ import annotations
import os, asyncio, time, threading
from dataclasses import dataclass, field
from typing import Dict, List, Iterable, Optional

from alpaca.data.live import StockDataStream
from app.alpaca_client import build_trading_client
from app.execution.alpaca_orders import submit_order_sync, build_market_order, build_limit_order
from app.streaming import _select_feed_with_probe

API_KEY = os.getenv("ALPACA_API_KEY")
API_SEC = os.getenv("ALPACA_API_SECRET")

def _staleness_threshold() -> float:
    try:
        return float(os.getenv("DATA_STALENESS_SEC", "5"))
    except Exception:
        return 5.0

@dataclass
class FeedSnapshot:
    feed: str
    latest: Dict[str, dict] = field(default_factory=dict)
    last_update: Dict[str, float] = field(default_factory=dict)
    latencies: Dict[str, List[float]] = field(default_factory=dict)
    stale: List[str] = field(default_factory=list)
    ok: List[str] = field(default_factory=list)

class StreamManager:
    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stream: Optional[StockDataStream] = None
        self._stop = threading.Event()
        self._symbols: List[str] = []
        self._feed_name = "?"
        self._latest: Dict[str, dict] = {}
        self._last_update: Dict[str, float] = {}
        self._lat: Dict[str, List[float]] = {}

    def start(self, symbols: Iterable[str]) -> None:
        if self.running:
            return
        syms = [s.strip().upper() for s in symbols if s.strip()]
        self._symbols = syms
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="gigatrader-stream", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._loop and self._stream:
            try:
                fut = asyncio.run_coroutine_threadsafe(self._stream.stop(), self._loop)
                fut.result(timeout=5)
            except Exception:
                pass

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def snapshot(self) -> FeedSnapshot:
        thr = _staleness_threshold()
        now = time.time()
        stale = []
        ok = []
        for s in self._symbols:
            last = self._last_update.get(s, 0)
            (stale if (now - last) > thr else ok).append(s)
        return FeedSnapshot(
            feed=self._feed_name,
            latest=self._latest.copy(),
            last_update=self._last_update.copy(),
            latencies={k: v[-200:] for k, v in self._lat.items()},
            stale=sorted(stale),
            ok=sorted(ok),
        )

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            feed = _select_feed_with_probe()
            self._feed_name = str(feed).split(".")[-1]
            self._stream = StockDataStream(API_KEY, API_SEC, feed=feed)

            async def on_bar(bar):
                try:
                    sym = bar.symbol.upper()
                    ingest = time.time()
                    evt_ts = getattr(bar, "timestamp", None)
                    if hasattr(evt_ts, "timestamp"):
                        latency = max(0.0, ingest - evt_ts.timestamp())
                    else:
                        latency = 0.0
                    self._last_update[sym] = ingest
                    self._lat.setdefault(sym, []).append(latency)
                    self._latest[sym] = {"close": float(bar.close), "ts": str(bar.timestamp)}
                except Exception:
                    pass

            self._stream.subscribe_bars(on_bar, *self._symbols)
            self._loop.run_until_complete(self._stream.run())
        finally:
            try:
                self._loop.stop()
            except Exception:
                pass

def get_account_summary() -> dict:
    client = build_trading_client()
    acct = client.get_account()
    return {
        "mode": "LIVE" if os.getenv("LIVE_TRADING","") == "true" else "PAPER",
        "id": getattr(acct, "id", "?"),
        "status": getattr(acct, "status", "?"),
        "buying_power": str(getattr(acct, "buying_power", "?")),
        "cash": str(getattr(acct, "cash", "?")),
        "portfolio_value": str(getattr(acct, "portfolio_value", "?")),
    }

def place_test_order(symbol: str, qty: int, type_: str, limit_price: float | None):
    if os.getenv("LIVE_TRADING","") == "true":
        raise RuntimeError("Refusing in LIVE mode. This action is paper-only.")
    client = build_trading_client()
    if type_.lower() == "market":
        req = build_market_order(symbol, qty, "buy", "DAY")
    elif type_.lower() == "limit":
        if limit_price is None:
            raise ValueError("Limit orders require a limit_price.")
        req = build_limit_order(symbol, qty, "buy", float(limit_price), "DAY")
    else:
        raise ValueError("type_ must be 'market' or 'limit'")
    o = submit_order_sync(client, req)
    return {"id": getattr(o, "id", "?"), "status": getattr(o, "status", "?")}
