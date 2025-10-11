"""Rolling sentiment store for per-symbol metrics."""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(slots=True)
class SentimentState:
    """Mutable state for a single symbol."""

    score: float = 0.0
    count: int = 0
    velocity: float = 0.0
    last_seen: float = 0.0


class SentiStore:
    """In-memory store maintaining rolling sentiment per symbol."""

    def __init__(self, ttl_min: int = 120, decay_per_min: float = 0.01) -> None:
        self.ttl = ttl_min * 60
        self.decay = decay_per_min
        self.by_symbol: Dict[str, SentimentState] = defaultdict(SentimentState)

    def _decay(self, symbol: str, now: float) -> None:
        state = self.by_symbol[symbol]
        if state.last_seen == 0:
            return
        minutes = max(0.0, (now - state.last_seen) / 60.0)
        decay_factor = max(0.0, 1.0 - self.decay * minutes)
        state.score *= decay_factor
        state.velocity *= decay_factor

    def upsert(self, symbol: str, value: float, now: float | None = None) -> None:
        now = now or time.time()
        self._decay(symbol, now)
        state = self.by_symbol[symbol]
        state.velocity = value - state.score
        state.score = max(-1.0, min(1.0, 0.5 * state.score + 0.5 * value))
        state.count += 1
        state.last_seen = now

    def get(self, symbol: str, now: float | None = None) -> Tuple[float, int, float]:
        now = now or time.time()
        state = self.by_symbol[symbol]
        if state.last_seen and (now - state.last_seen) > self.ttl:
            return 0.0, 0, 0.0
        self._decay(symbol, now)
        return state.score, state.count, state.velocity
