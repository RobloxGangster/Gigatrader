from __future__ import annotations

import json
import logging
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

logger = logging.getLogger(__name__)


class IMarketDataClient(Protocol):
    def get_bars(self, symbol: str, timeframe: str, limit: int = 500) -> list[dict[str, Any]]: ...

    def get_quote(self, symbol: str) -> dict[str, Any]: ...

    def get_option_chain(self, underlying: str, expiry: str | None = None) -> dict[str, Any]: ...


FIXTURE_DIR = Path("fixtures")


@dataclass
class MockDataClient:
    """Loads deterministic market data from local fixtures for offline tests."""

    base_dir: Path = FIXTURE_DIR

    def _load_csv(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            raise FileNotFoundError(path)
        df = pd.read_csv(path)
        return df.to_dict(orient="records")

    def get_bars(self, symbol: str, timeframe: str, limit: int = 500) -> list[dict[str, Any]]:
        records = self._load_csv(self.base_dir / f"bars_{symbol.upper()}.csv")
        return records[-limit:]

    def get_quote(self, symbol: str) -> dict[str, Any]:
        records = self._load_csv(self.base_dir / f"quotes_{symbol.upper()}.csv")
        return records[-1]

    def get_option_chain(self, underlying: str, expiry: str | None = None) -> dict[str, Any]:
        path = self.base_dir / f"chain_{underlying.upper()}.json"
        if not path.exists():
            return {"underlying": underlying, "options": []}
        data = json.loads(path.read_text())
        if expiry:
            data["options"] = [opt for opt in data.get("options", []) if opt.get("expiry") == expiry]
        return data


class AlpacaDataClient:
    """Thin wrapper around Alpaca's market data client."""

    def __init__(self) -> None:
        try:
            from alpaca.data import StockHistoricalDataClient
            from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
        except Exception as exc:  # pragma: no cover - exercised by fallback path
            raise RuntimeError("alpaca_data_unavailable") from exc

        self._client = StockHistoricalDataClient()
        self._bars_request = StockBarsRequest
        self._quote_request = StockLatestQuoteRequest

    def get_bars(self, symbol: str, timeframe: str, limit: int = 500) -> list[dict[str, Any]]:
        request = self._bars_request(symbol_or_symbols=symbol, timeframe=timeframe, limit=limit)
        bars = self._client.get_stock_bars(request).df
        bars = bars.reset_index()
        return bars.to_dict(orient="records")

    def get_quote(self, symbol: str) -> dict[str, Any]:
        request = self._quote_request(symbol_or_symbols=symbol)
        quote = self._client.get_stock_latest_quote(request)
        if isinstance(quote, dict):
            return next(iter(quote.values()))
        return quote.model_dump()

    def get_option_chain(self, underlying: str, expiry: str | None = None) -> dict[str, Any]:  # pragma: no cover - requires network
        raise NotImplementedError("Option chain retrieval requires custom integration")


def _truthy(name: str) -> bool:
    v = os.getenv(name, "").strip().lower()
    return v in {"1", "true", "yes", "on"}


def build_data_client(mock_mode: bool = False) -> IMarketDataClient:
    if mock_mode or _truthy("MOCK_MODE"):
        logger.info("market: MOCK_MODE -> MockDataClient")
        return MockDataClient()

    api_key = os.getenv("APCA_API_KEY_ID", "").strip()
    api_secret = os.getenv("APCA_API_SECRET_KEY", "").strip()

    if not api_key or not api_secret:
        logger.info("market: alpaca creds missing -> mock")
        return MockDataClient()

    try:
        logger.info("market: attempting AlpacaDataClient")
        return AlpacaDataClient()
    except Exception as exc:  # noqa: BLE001
        logger.info("market: AlpacaDataClient unavailable (%s) -> mock", exc)
        return MockDataClient()


def bars_to_df(bars: list[dict[str, Any]]) -> pd.DataFrame:
    if not bars:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(bars)
    if "timestamp" in df.columns and "time" not in df.columns:
        df = df.rename(columns={"timestamp": "time"})
    df["time"] = pd.to_datetime(df["time"]).dt.tz_localize(None)
    numeric_cols = [col for col in df.columns if col != "time"]
    df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors="coerce")
    df = df.sort_values("time").reset_index(drop=True)
    return df
