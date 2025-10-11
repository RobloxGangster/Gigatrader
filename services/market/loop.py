"""Async market data loop for Alpaca feeds."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import yaml
from alpaca.data.live import StockDataStream
from alpaca.data.models.bars import Bar

from app.config import get_settings
from services.market.indicators import OpeningRange, RollingATR, RollingRSI, RollingZScore
from services.market.store import BarRow, TSStore

_MAX_BACKOFF_SECONDS = 60


class MarketLoop:
    """Manage streaming market data and indicator persistence."""

    def __init__(self, cfg: Dict[str, Any], ts_url: str) -> None:
        self.cfg = self._resolve_config(cfg)
        self.store = TSStore(ts_url)
        self.symbol_state: Dict[str, Dict[str, Any]] = {}
        self.msgs = 0
        self.last_metrics = time.time()
        self.heartbeat: Optional[float] = None
        self._backoff = 1.0

    @staticmethod
    def _resolve_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
        resolved: Dict[str, Any] = {}
        for key, value in cfg.items():
            resolved[key] = MarketLoop._resolve_value(value)

        resolved["symbols"] = [s.strip().upper() for s in str(resolved["symbols"]).split(",") if s.strip()]
        resolved["orb_minutes"] = int(resolved["orb_minutes"])
        resolved["rsi_period"] = int(resolved["rsi_period"])
        resolved["atr_period"] = int(resolved["atr_period"])
        resolved["zscore_window"] = int(resolved["zscore_window"])
        resolved["metrics_interval_sec"] = int(resolved["metrics_interval_sec"])
        resolved["bar_timeframe"] = str(resolved.get("bar_timeframe", "1Min"))
        return resolved

    @staticmethod
    def _resolve_value(value: Any) -> Any:
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            inner = value[2:-1]
            if ":-" in inner:
                env_var, default = inner.split(":-", 1)
                return os.getenv(env_var, default)
            return os.getenv(inner, "")
        return value

    def _ensure_state(self, symbol: str) -> Dict[str, Any]:
        if symbol not in self.symbol_state:
            self.symbol_state[symbol] = {
                "rsi": RollingRSI(self.cfg["rsi_period"]),
                "atr": RollingATR(self.cfg["atr_period"]),
                "zscore": RollingZScore(self.cfg["zscore_window"]),
                "orb": OpeningRange(self.cfg["orb_minutes"]),
                "session_date": None,
            }
        return self.symbol_state[symbol]

    async def run(self) -> None:
        settings = get_settings()
        stream = StockDataStream(
            settings.alpaca_key_id,
            settings.alpaca_secret_key,
            feed=settings.data_feed,
        )

        for symbol in self.cfg["symbols"]:
            stream.subscribe_bars(self._on_bar_factory(symbol))

        while True:
            try:
                print(
                    f"[market] connecting feed={settings.data_feed} symbols={self.cfg['symbols']}"
                )
                await stream.run()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - runtime resilience
                delay = min(self._backoff, _MAX_BACKOFF_SECONDS)
                print(f"[market] error: {exc}; reconnecting in {delay:.1f}s")
                await asyncio.sleep(delay)
                self._backoff = min(self._backoff * 2, _MAX_BACKOFF_SECONDS)
            else:
                print("[market] stream ended; reconnecting")
                await asyncio.sleep(self._backoff)
                self._backoff = min(self._backoff * 2, _MAX_BACKOFF_SECONDS)

    def _on_bar_factory(self, symbol: str):
        async def handler(bar: Bar) -> None:
            state = self._ensure_state(symbol)
            session_date = bar.timestamp.date()
            if state["session_date"] != session_date:
                state["session_date"] = session_date
                state["orb"].reset()

            rsi = state["rsi"].update(float(bar.close))
            atr = state["atr"].update(float(bar.high), float(bar.low), float(bar.close))
            zscore = state["zscore"].update(float(bar.close))
            orb_state = state["orb"].update(float(bar.high), float(bar.low))
            breakout = state["orb"].breakout(float(bar.close))

            self.store.write(
                BarRow(
                    symbol=symbol,
                    ts=bar.timestamp.isoformat(),
                    open=float(bar.open),
                    high=float(bar.high),
                    low=float(bar.low),
                    close=float(bar.close),
                    volume=float(bar.volume or 0.0),
                    rsi=rsi,
                    atr=atr,
                    zscore=zscore,
                    orb_state=orb_state,
                    orb_breakout=breakout,
                )
            )

            self.msgs += 1
            self.heartbeat = time.time()
            await self._metrics_maybe(bar)

        return handler

    async def _metrics_maybe(self, bar: Bar) -> None:
        now = time.time()
        if now - self.last_metrics >= self.cfg["metrics_interval_sec"]:
            lag = (datetime.now(timezone.utc) - bar.timestamp).total_seconds()
            rate = self.msgs / max(1, self.cfg["metrics_interval_sec"])
            print(
                f"[metrics] msgs/sec≈{rate:.2f} lag_s={lag:.2f} heartbeat={self.heartbeat:.2f}"
            )
            self.msgs = 0
            self.last_metrics = now
            self._backoff = 1.0


def main() -> None:
    ts_url = os.getenv("TIMESCALE_URL", "")
    if not ts_url:
        raise SystemExit("TIMESCALE_URL is required")
    with open("configs/market.yaml", "r", encoding="utf-8") as handle:
        cfg = yaml.safe_load(handle)
    loop = MarketLoop(cfg, ts_url)
    asyncio.run(loop.run())


if __name__ == "__main__":  # pragma: no cover - manual execution entry point
    main()
