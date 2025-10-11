"""Fetchers for sentiment pipeline (stub implementations)."""
from __future__ import annotations

import time
from typing import List, Sequence

from services.sentiment.types import NewsItem


class StubFetcher:
    """Simple stub fetcher generating deterministic positive headlines."""

    def __init__(self, source_name: str = "stub") -> None:
        self.source = source_name

    def fetch(self, symbols: Sequence[str], max_minutes: int = 60) -> List[NewsItem]:
        del max_minutes
        now = time.time()
        items: List[NewsItem] = []
        for symbol in symbols:
            items.append(
                NewsItem(
                    id=f"{self.source}-{symbol}-{int(now)}",
                    source=self.source,
                    ts=now,
                    symbol=symbol,
                    title=f"{symbol} beats estimates on strong growth",
                    summary=None,
                )
            )
        return items
