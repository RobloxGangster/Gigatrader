"""Alpaca market data adapter."""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Iterable, List

from alpaca.data.historical import StockHistoricalDataClient, OptionHistoricalDataClient
from alpaca.data.live import StockDataStream, OptionDataStream
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from core.interfaces import DataProvider

logger = logging.getLogger(__name__)


class AlpacaDataProvider(DataProvider):
    """Fetches equities and options data from Alpaca.

    TODO: Wire in authentication and pagination; handle retries on network errors.
    """

    def __init__(self, stock_client: StockHistoricalDataClient, option_client: OptionHistoricalDataClient) -> None:
        self._stock_client = stock_client
        self._option_client = option_client
        self._stock_stream: StockDataStream | None = None
        self._option_stream: OptionDataStream | None = None

    async def get_bars(self, symbol: str, timeframe: str) -> Iterable[dict]:
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame[timeframe.upper()],
            limit=1000,
        )
        response = await asyncio.to_thread(self._stock_client.get_stock_bars, request)
        return [bar.dict() for bar in response]

    async def get_snapshot(self, symbol: str) -> dict:
        # TODO: Implement snapshot retrieval using alpaca-py once available for options.
        raise NotImplementedError

    def stream_quotes(self, symbols: List[str]) -> AsyncIterator[dict]:
        if not self._stock_stream:
            raise RuntimeError("StockDataStream not initialised")
        return self._stock_stream.subscribe_quotes(symbols)

    def stream_trades(self, symbols: List[str]) -> AsyncIterator[dict]:
        if not self._stock_stream:
            raise RuntimeError("StockDataStream not initialised")
        return self._stock_stream.subscribe_trades(symbols)

    def stream_bars(self, symbols: List[str], timeframe: str) -> AsyncIterator[dict]:
        if not self._stock_stream:
            raise RuntimeError("StockDataStream not initialised")
        return self._stock_stream.subscribe_bars(symbols, TimeFrame[timeframe.upper()])

    async def get_option_chain(self, underlier: str, expiry: str) -> dict:
        # TODO: Query Alpaca options chain and normalise payload.
        raise NotImplementedError

    async def get_option_greeks(self, contract: str) -> dict:
        # TODO: Query Alpaca option greeks.
        raise NotImplementedError

    async def ensure_streams(self, key: str, secret: str, paper: bool = True) -> None:
        """Initialise websocket streams. Fail closed when connection fails."""

        try:
            self._stock_stream = StockDataStream(key, secret, paper=paper)
            self._option_stream = OptionDataStream(key, secret, paper=paper)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to initialise Alpaca streams", exc_info=exc)
            raise
