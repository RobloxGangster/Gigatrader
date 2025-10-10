"""Paper-mode market data smoke test."""
from __future__ import annotations

from alpaca.data.live import StockDataStream
from alpaca.data.live.stock import DataFeed
from alpaca.data.models.bars import Bar

from app.config import get_settings

MAX_MESSAGES = 6


def main() -> None:
    """Run the smoke test against the Alpaca Market Data WebSocket."""

    cfg = get_settings()
    try:
        feed = DataFeed(cfg.data_feed.lower())
    except ValueError as exc:
        raise RuntimeError(f"Unsupported data feed '{cfg.data_feed}'.") from exc

    stream = StockDataStream(cfg.alpaca_key_id, cfg.alpaca_secret_key, feed=feed)
    received = {"count": 0}

    async def on_bar(bar: Bar) -> None:
        received["count"] += 1
        print(
            f"[BAR] {bar.symbol} {bar.timestamp} o:{bar.open} h:{bar.high} "
            f"l:{bar.low} c:{bar.close} v:{bar.volume}"
        )
        if received["count"] >= MAX_MESSAGES:
            stream.stop()

    for sym in cfg.smoke_symbols:
        stream.subscribe_bars(on_bar, sym)

    mode = "PAPER" if cfg.paper else "LIVE"
    print(
        f"Connecting to Alpaca Market Data ({cfg.data_feed}) for {cfg.smoke_symbols} in {mode} mode..."
    )
    stream.run()
    print("Smoke test complete.")


if __name__ == "__main__":
    main()
