"""Integration tests for sentiment pipeline."""

from __future__ import annotations

from services.sentiment.fetchers import StubFetcher
from services.sentiment.poller import Poller
from services.sentiment.store import SentiStore


def test_pipeline_updates_store() -> None:
    store = SentiStore(ttl_min=120, decay_per_min=0.0)
    poller = Poller(
        store=store, fetchers=[StubFetcher("stub1"), StubFetcher("stub2")], symbols=["AAPL", "MSFT"]
    )
    result = poller.run_once(now=1000.0)

    score, count, velocity = store.get("AAPL", now=1001.0)
    assert count >= 1
    assert -1.0 <= score <= 1.0
    assert velocity != 0.0
    assert set(result.keys()) >= {"AAPL", "MSFT"}
