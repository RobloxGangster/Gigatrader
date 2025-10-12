"""News-first poller for sentiment scoring."""

from __future__ import annotations

import os
import threading
import time
from typing import Dict, Iterable, List, Sequence, Set

from services.sentiment.filters import dedupe, language_filter, source_whitelist
from services.sentiment.hf_model import infer as hf_infer
from services.sentiment.onnx_model import infer as onnx_infer
from services.sentiment.rule_model import infer as rule_infer
from services.sentiment.store import SentiStore
from services.sentiment.types import NewsItem, ScoredItem


class Poller:
    """Coordinate fetching, filtering, scoring, and storing sentiment."""

    def __init__(
        self,
        store: SentiStore,
        fetchers: Iterable[object],
        symbols: Sequence[str],
    ) -> None:
        self.store = store
        self.fetchers = list(fetchers)
        self.symbols = list(symbols)
        self.interval = int(os.getenv("SENTI_POLL_SEC", "30"))
        self.lang = os.getenv("SENTI_LANG", "en")
        whitelist = os.getenv("SENTI_SOURCE_WHITELIST", "").strip()
        self.whitelist: Set[str] = {
            entry.strip() for entry in whitelist.split(",") if entry.strip()
        }
        self.model = os.getenv("SENTI_MODEL", "rule").strip().lower()
        self.hf_name = os.getenv("SENTI_HF_MODEL", "ProsusAI/finbert")
        self.onnx_path = os.getenv("SENTI_ONNX_PATH", "models/finbert.onnx")
        self.max_backfill = int(os.getenv("SENTI_MAX_BACKFILL_MIN", "60"))

    def _score(self, item: NewsItem) -> ScoredItem:
        text = f"{item.title} {item.summary or ''}".strip()
        if self.model == "hf":
            return hf_infer(item, self.hf_name)
        if self.model == "onnx":
            scores = onnx_infer(text, self.onnx_path)
            value = scores.get("positive", 0.0) - scores.get("negative", 0.0)
            if value > 0.1:
                label = "pos"
            elif value < -0.1:
                label = "neg"
            else:
                label = "neu"
            return ScoredItem(
                item=item,
                label=label,
                score=float(value),
                model=f"onnx:{self.onnx_path}",
                features=scores,
            )
        return rule_infer(item)

    def run_once(self, now: float | None = None) -> Dict[str, List[ScoredItem]]:
        """Run a single polling cycle."""
        now = now or time.time()
        items: List[NewsItem] = []
        for fetcher in self.fetchers:
            try:
                fetched = fetcher.fetch(self.symbols, max_minutes=self.max_backfill)
            except Exception:
                continue
            items.extend(fetched)
        items = dedupe(source_whitelist(language_filter(items, self.lang), self.whitelist))
        per_symbol: Dict[str, List[ScoredItem]] = {}
        for item in items:
            scored = self._score(item)
            self.store.upsert(item.symbol, scored.score, now)
            per_symbol.setdefault(item.symbol, []).append(scored)
        return per_symbol

    def serve_forever(self) -> None:
        """Background loop for continuous polling."""
        while True:
            self.run_once()
            time.sleep(self.interval)

    def start_background(self) -> threading.Thread:
        """Start a background thread that polls indefinitely."""
        thread = threading.Thread(target=self.serve_forever, daemon=True)
        thread.start()
        return thread
