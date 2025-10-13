"""Sentiment poller that fetches Alpaca news headlines and scores them."""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Dict, List, Optional, Sequence

from services.sentiment.fetchers import AlpacaNewsFetcher
from services.sentiment.rule_model import infer as rule_infer
from services.sentiment.store import SentiStore
from services.sentiment.types import NewsItem, ScoredItem


class Poller:
    """Fetch Alpaca headlines for configured symbols and score them."""

    def __init__(
        self,
        store: SentiStore,
        symbols: Sequence[str],
        fetcher: Optional[AlpacaNewsFetcher] = None,
    ) -> None:
        self.store = store
        self.symbols = list(symbols)
        self.interval = int(os.getenv("SENTI_POLL_SEC", "300"))
        self.lookback_hours = int(os.getenv("SENTI_NEWS_LOOKBACK_HRS", "6"))
        self.fetcher = fetcher or self._build_fetcher()
        self.log = logging.getLogger("gigatrader.sentiment")

    def _build_fetcher(self) -> AlpacaNewsFetcher:
        api_key = os.environ["ALPACA_API_KEY_ID"]
        secret = os.environ["ALPACA_API_SECRET_KEY"]
        return AlpacaNewsFetcher(api_key=api_key, secret=secret)

    def _score_headline(self, symbol: str, headline: str, ts: float) -> ScoredItem:
        item = NewsItem(
            id=f"alpaca:{symbol}:{int(ts)}:{abs(hash(headline)) & 0xffff}",
            source="alpaca",
            ts=ts,
            symbol=symbol,
            title=headline,
        )
        return rule_infer(item)

    def run_once(self, now: Optional[float] = None) -> Dict[str, List[ScoredItem]]:
        now = now or time.time()
        per_symbol: Dict[str, List[ScoredItem]] = {}
        for symbol in self.symbols:
            try:
                headlines = self.fetcher.fetch_headlines(symbol, hours_back=self.lookback_hours)
            except Exception as exc:  # pragma: no cover - network errors
                self.log.warning(
                    "sentiment.fetch_failed",
                    extra={"symbol": symbol, "error": str(exc)},
                )
                per_symbol[symbol] = []
                continue
            if not headlines:
                per_symbol[symbol] = []
                continue
            scored_items: List[ScoredItem] = []
            for headline in headlines:
                scored = self._score_headline(symbol, headline, now)
                scored_items.append(scored)
                self.store.upsert(symbol, scored.score, now)
            per_symbol[symbol] = scored_items
        return per_symbol

    def serve_forever(self) -> None:
        while True:
            self.run_once()
            time.sleep(self.interval)

    def start_background(self) -> threading.Thread:
        thread = threading.Thread(target=self.serve_forever, daemon=True)
        thread.start()
        return thread
