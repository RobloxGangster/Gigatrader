from __future__ import annotations
from datetime import datetime, timedelta, timezone
import os

class AlpacaNewsFetcher:
    """
    Fetch recent headlines from Alpaca News via alpaca-py.
    Gracefully degrades if NewsClient is unavailable.
    """
    def __init__(self):
        self.api_key = os.environ.get("ALPACA_API_KEY_ID")
        self.api_secret = os.environ.get("ALPACA_API_SECRET_KEY")
        if not self.api_key or not self.api_secret:
            raise RuntimeError("Missing ALPACA_API_KEY_ID/ALPACA_API_SECRET_KEY")

        # Resolve a News client across alpaca-py versions
        self.NewsClient = None
        self.NewsRequest = None
        self._import_news_client()

    def _import_news_client(self):
        err = []
        try:
            # newer layout
            from alpaca.data.historical.news import NewsClient as NC
            from alpaca.data.requests import NewsRequest as NR
            self.NewsClient, self.NewsRequest = NC, NR
            return
        except Exception as e:
            err.append(str(e))
        try:
            # fallback older layout
            from alpaca.data import NewsClient as NC
            from alpaca.data.requests import NewsRequest as NR
            self.NewsClient, self.NewsRequest = NC, NR
            return
        except Exception as e:
            err.append(str(e))
        raise RuntimeError(f"alpaca-py NewsClient not available: {' | '.join(err)}")

    def fetch_headlines(self, symbol: str, hours_back: int = 24, limit: int = 50):
        start = datetime.now(timezone.utc) - timedelta(hours=hours_back)
        end = datetime.now(timezone.utc)
        client = self.NewsClient(self.api_key, self.api_secret)
        req = self.NewsRequest(
            symbols=[symbol],
            start=start,
            end=end,
            limit=limit,
            include_content=False
        )
        # The exact return shape can vary; normalize to {headline, summary, id, updated_at}
        res = client.get_news(req)
        items = []
        for item in list(res) if not isinstance(res, list) else res:
            try:
                headline = getattr(item, "headline", None) or getattr(item, "title", "")
                summary = getattr(item, "summary", "") or getattr(item, "author", "")
                nid = getattr(item, "id", None) or getattr(item, "uuid", "")
                updated = getattr(item, "updated_at", None) or getattr(item, "created_at", None)
                items.append({
                    "id": str(nid),
                    "headline": str(headline) if headline is not None else "",
                    "summary": str(summary) if summary is not None else "",
                    "updated_at": str(updated) if updated is not None else ""
                })
            except Exception:
                # best-effort if the object is a plain dict
                if isinstance(item, dict):
                    items.append({
                        "id": str(item.get("id","")),
                        "headline": str(item.get("headline") or item.get("title") or ""),
                        "summary": str(item.get("summary") or ""),
                        "updated_at": str(item.get("updated_at") or item.get("created_at") or "")
                    })
        return items
