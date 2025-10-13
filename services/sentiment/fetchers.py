from __future__ import annotations
from datetime import datetime, timedelta, timezone
import os

class AlpacaNewsFetcher:
    """
    Fetch recent headlines from Alpaca News via alpaca-py.
    Robust to version differences in NewsClient/NewsRequest signatures.
    """

    def __init__(self):
        self.api_key = os.environ.get("ALPACA_API_KEY_ID")
        self.api_secret = os.environ.get("ALPACA_API_SECRET_KEY")
        if not self.api_key or not self.api_secret:
            raise RuntimeError("Missing ALPACA_API_KEY_ID/ALPACA_API_SECRET_KEY")
        self.NewsClient = None
        self.NewsRequest = None
        self._import_news_client()

    def _import_news_client(self):
        errors = []
        try:
            # newer layout (common on recent alpaca-py)
            from alpaca.data.historical.news import NewsClient as NC
            from alpaca.data.requests import NewsRequest as NR
            self.NewsClient, self.NewsRequest = NC, NR
            return
        except Exception as e:
            errors.append(f"newer layout: {e}")
        try:
            # older layout fallback
            from alpaca.data import NewsClient as NC
            from alpaca.data.requests import NewsRequest as NR
            self.NewsClient, self.NewsRequest = NC, NR
            return
        except Exception as e:
            errors.append(f"older layout: {e}")
        raise RuntimeError("alpaca-py NewsClient not available: " + " | ".join(errors))

    def _make_client(self):
        """
        Build a NewsClient. Some versions accept (api_key, api_secret),
        others rely on env vars and take no args.
        """
        # Try explicit keys first
        try:
            return self.NewsClient(self.api_key, self.api_secret)
        except TypeError:
            # Try without args (env-based)
            return self.NewsClient()

    def _build_request(self, symbol: str, start, end, limit: int):
        """
        Construct NewsRequest across schema differences:
        1) symbols=["AAPL"]
        2) symbols="AAPL"
        3) symbol="AAPL"  (older)
        """
        NR = self.NewsRequest
        # Attempt 1: list form
        try:
            return NR(symbols=[symbol], start=start, end=end, limit=limit, include_content=False)
        except Exception:
            pass
        # Attempt 2: string form
        try:
            return NR(symbols=symbol, start=start, end=end, limit=limit, include_content=False)
        except Exception:
            pass
        # Attempt 3: singular arg
        try:
            return NR(symbol=symbol, start=start, end=end, limit=limit, include_content=False)
        except Exception as e:
            raise RuntimeError(f"Could not build NewsRequest for symbol={symbol}: {e}")

    def fetch_headlines(self, symbol: str, hours_back: int = 24, limit: int = 50):
        start = datetime.now(timezone.utc) - timedelta(hours=hours_back)
        end = datetime.now(timezone.utc)
        client = self._make_client()
        req = self._build_request(symbol, start, end, limit)
        res = client.get_news(req)

        # Normalize to list of dicts
        seq = list(res) if not isinstance(res, list) else res
        items = []
        for item in seq:
            try:
                headline = getattr(item, "headline", None) or getattr(item, "title", "") or ""
                summary  = getattr(item, "summary", "") or ""
                nid      = getattr(item, "id", None) or getattr(item, "uuid", "") or ""
                updated  = getattr(item, "updated_at", None) or getattr(item, "created_at", None) or ""
                items.append({
                    "id": str(nid),
                    "headline": str(headline),
                    "summary": str(summary),
                    "updated_at": str(updated)
                })
            except Exception:
                if isinstance(item, dict):
                    items.append({
                        "id": str(item.get("id","")),
                        "headline": str(item.get("headline") or item.get("title") or ""),
                        "summary": str(item.get("summary") or ""),
                        "updated_at": str(item.get("updated_at") or item.get("created_at") or "")
                    })
        return items
