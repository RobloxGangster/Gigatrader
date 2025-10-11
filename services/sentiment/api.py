"""Public API surface for sentiment consumers."""
from __future__ import annotations

from typing import Tuple

from services.sentiment.store import SentiStore


class SentiAPI:
    """Simple sentiment API wrapper."""

    def __init__(self, store: SentiStore) -> None:
        self.store = store

    def get_sentiment(self, symbol: str) -> Tuple[float, int, float]:
        return self.store.get(symbol)
