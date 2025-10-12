"""Filtering utilities for sentiment ingestion."""

from __future__ import annotations

from typing import Iterable, List, Set

from services.sentiment.types import NewsItem


def language_filter(items: Iterable[NewsItem], lang: str) -> List[NewsItem]:
    """Filter news items by language prefix (case-insensitive)."""
    if not lang:
        return list(items)
    lang_lower = lang.lower()
    return [x for x in items if (x.lang or "en").lower().startswith(lang_lower)]


def source_whitelist(items: Iterable[NewsItem], allowed: Set[str]) -> List[NewsItem]:
    """Filter news items by a set of allowed source identifiers."""
    if not allowed:
        return list(items)
    lowered = {s.lower() for s in allowed}
    return [x for x in items if x.source.lower() in lowered]


def dedupe(items: Iterable[NewsItem]) -> List[NewsItem]:
    """Deduplicate news items by (source, id)."""
    seen: Set[tuple[str, str]] = set()
    out: List[NewsItem] = []
    for item in items:
        key = (item.source, item.id)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
