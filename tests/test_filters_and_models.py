"""Unit tests for filters and rule-based scoring."""

from __future__ import annotations

from services.sentiment.filters import dedupe, language_filter, source_whitelist
from services.sentiment.rule_model import score_text
from services.sentiment.types import NewsItem


def test_filters_and_rule_scoring() -> None:
    items = [
        NewsItem(
            id="1",
            source="reuters",
            ts=1.0,
            symbol="AAPL",
            title="AAPL beats on strong growth",
            lang="en",
        ),
        NewsItem(
            id="1",
            source="reuters",
            ts=1.0,
            symbol="AAPL",
            title="AAPL beats on strong growth",
            lang="en",
        ),
        NewsItem(
            id="2",
            source="random",
            ts=1.0,
            symbol="AAPL",
            title="AAPL downgrade amidst slump",
            lang="en",
        ),
        NewsItem(id="3", source="reuters", ts=1.0, symbol="AAPL", title="Unrelated", lang="fr"),
    ]
    items = dedupe(items)
    assert len(items) == 3

    items = source_whitelist(items, {"reuters"})
    assert all(item.source == "reuters" for item in items)

    items = language_filter(items, "en")
    assert all((item.lang or "en").lower().startswith("en") for item in items)

    assert score_text("record surge growth") > 0
    assert score_text("fraud lawsuit slump") < 0
