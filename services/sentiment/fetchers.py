"""Fetchers for sentiment pipeline (stub implementations)."""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Sequence

from services.sentiment.types import NewsItem

try:  # Optional dependency: requests
    import requests

    _RequestError = requests.RequestException
except Exception:  # pragma: no cover - exercised when requests missing
    requests = None  # type: ignore[assignment]
    _RequestError = Exception


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


class NewsAPIFetcher:
    """Minimal NewsAPI.org fetcher for live sentiment when credentials exist."""

    def __init__(self, api_key: str, *, session: Optional[Any] = None) -> None:
        self.api_key = api_key
        if requests is None:
            raise RuntimeError("requests dependency required for NewsAPIFetcher")
        self.session = session or requests.Session()
        self.endpoint = os.getenv("NEWS_API_URL", "https://newsapi.org/v2/everything")
        self.page_size = int(os.getenv("NEWS_API_PAGE_SIZE", "10"))
        self.language = os.getenv("NEWS_API_LANGUAGE", "en")
        self.timeout = float(os.getenv("NEWS_API_TIMEOUT", "5"))
        self.source_name = "newsapi"

    def fetch(self, symbols: Sequence[str], max_minutes: int = 60) -> List[NewsItem]:
        if not symbols:
            return []
        params_base = {
            "apiKey": self.api_key,
            "language": self.language,
            "pageSize": self.page_size,
            "sortBy": "publishedAt",
        }
        items: List[NewsItem] = []
        since: Optional[datetime] = None
        if max_minutes > 0:
            since = datetime.now(timezone.utc) - timedelta(minutes=max_minutes)
        for symbol in symbols:
            params = dict(params_base)
            params["q"] = symbol
            if since is not None:
                params["from"] = since.isoformat(timespec="seconds")
            try:
                response = self.session.get(
                    self.endpoint,
                    params=params,
                    timeout=self.timeout,
                )
                response.raise_for_status()
            except _RequestError:
                continue
            payload = response.json()
            for article in payload.get("articles", []):
                published_at = article.get("publishedAt") or ""
                try:
                    ts = datetime.fromisoformat(published_at.replace("Z", "+00:00")).timestamp()
                except Exception:
                    ts = time.time()
                items.append(
                    NewsItem(
                        id=article.get("url") or f"{self.source_name}-{symbol}-{int(ts)}",
                        source=(article.get("source") or {}).get("name") or self.source_name,
                        ts=ts,
                        symbol=symbol,
                        title=article.get("title") or f"{symbol} news update",
                        summary=article.get("description"),
                        url=article.get("url"),
                        lang=self.language,
                    )
                )
        return items
