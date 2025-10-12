"""Dataclasses for sentiment processing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(slots=True)
class NewsItem:
    """Normalized news item ingested from upstream fetchers."""

    id: str
    source: str
    ts: float
    symbol: str
    title: str
    summary: Optional[str] = None
    url: Optional[str] = None
    lang: str = "en"


@dataclass(slots=True)
class ScoredItem:
    """Scored news item with sentiment metadata."""

    item: NewsItem
    label: str  # pos|neu|neg
    score: float  # [-1, 1]
    model: str
    features: Dict[str, float]
