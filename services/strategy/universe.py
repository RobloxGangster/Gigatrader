"""Universe management helpers for the strategy layer."""

from __future__ import annotations

from collections import OrderedDict
from typing import Iterable, List, Mapping


class Universe:
    """Maintain a dynamic watchlist seeded from a base set of symbols."""

    def __init__(self, base: Iterable[str], max_watch: int = 25) -> None:
        symbols = [sym.strip().upper() for sym in base if sym]
        self.base = list(dict.fromkeys(symbols))
        self.max_watch = max(1, max_watch)
        self.watchlist: List[str] = list(self.base)
        self._sync_watchset()

    def _sync_watchset(self) -> None:
        self._watchset = {sym.upper() for sym in self.watchlist}

    def update_with_sentiment(self, sentiment: Mapping[str, float]) -> None:
        """Expand the watchlist using the strongest sentiment readings."""

        ranked = sorted(
            ((symbol.strip().upper(), score) for symbol, score in sentiment.items() if symbol),
            key=lambda item: abs(item[1]),
            reverse=True,
        )
        seen = OrderedDict((sym, None) for sym in self.watchlist)
        for symbol, _ in ranked:
            seen.setdefault(symbol, None)
            if len(seen) >= self.max_watch:
                break
        self.watchlist = list(seen.keys())[: self.max_watch]
        self._sync_watchset()

    def get(self) -> List[str]:
        """Return a copy of the current watchlist."""

        return list(self.watchlist)

    def contains(self, symbol: str) -> bool:
        return symbol.strip().upper() in self._watchset
