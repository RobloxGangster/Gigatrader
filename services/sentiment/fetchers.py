from datetime import datetime, timedelta, timezone
from alpaca.data.historical.news import NewsClient, NewsRequest


class AlpacaNewsFetcher:
    def __init__(self, api_key: str, secret: str):
        self.client = NewsClient(api_key, secret)

    def fetch_headlines(self, symbol: str, hours_back: int = 6):
        start = datetime.now(timezone.utc) - timedelta(hours=hours_back)
        req = NewsRequest(symbols=[symbol], start=start)
        news = self.client.get_news(req)
        return [n.headline for n in news]
