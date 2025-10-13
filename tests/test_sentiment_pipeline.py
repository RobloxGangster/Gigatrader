"""Integration tests for sentiment pipeline."""

from __future__ import annotations

import sys
import types
from typing import Dict, List

# Provide a lightweight stub for alpaca.data.historical.news so imports succeed in tests.
_alpaca_module = types.ModuleType("alpaca")
_alpaca_data = types.ModuleType("alpaca.data")
_alpaca_hist = types.ModuleType("alpaca.data.historical")
_alpaca_news = types.ModuleType("alpaca.data.historical.news")


class _DummyNewsClient:  # pragma: no cover - only needed for import scaffolding
    def __init__(self, *args, **kwargs) -> None:  # noqa: D401 - simple stub
        raise RuntimeError("Dummy client should not be instantiated in tests")


class _DummyNewsRequest:  # pragma: no cover - only needed for import scaffolding
    def __init__(self, *args, **kwargs) -> None:
        pass


_alpaca_news.NewsClient = _DummyNewsClient
_alpaca_news.NewsRequest = _DummyNewsRequest
sys.modules.setdefault("alpaca", _alpaca_module)
sys.modules.setdefault("alpaca.data", _alpaca_data)
sys.modules.setdefault("alpaca.data.historical", _alpaca_hist)
sys.modules.setdefault("alpaca.data.historical.news", _alpaca_news)

from services.sentiment.poller import Poller
from services.sentiment.store import SentiStore


class _StaticFetcher:
    """Test helper that returns deterministic headlines."""

    def __init__(self, headlines: Dict[str, List[str]]) -> None:
        self.headlines = headlines

    def fetch_headlines(self, symbol: str, hours_back: int = 6) -> List[str]:
        return list(self.headlines.get(symbol, []))


def test_pipeline_updates_store() -> None:
    store = SentiStore(ttl_min=120, decay_per_min=0.0)
    fetcher = _StaticFetcher(
        {
            "AAPL": ["AAPL beats expectations on strong growth"],
            "MSFT": ["MSFT misses expectations as sales slump"],
        }
    )
    poller = Poller(store=store, symbols=["AAPL", "MSFT"], fetcher=fetcher)
    result = poller.run_once(now=1000.0)

    score, count, velocity = store.get("AAPL", now=1001.0)
    assert count >= 1
    assert -1.0 <= score <= 1.0
    assert velocity != 0.0
    assert set(result.keys()) >= {"AAPL", "MSFT"}
