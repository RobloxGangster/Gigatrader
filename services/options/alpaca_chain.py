"""Alpaca-backed option chain source."""

from __future__ import annotations

import asyncio
import datetime as _dt
from typing import List, Optional

from app.config import get_settings
from services.options.chain import ChainSource, OptionContract


def _calculate_mid(bid: Optional[float], ask: Optional[float]) -> Optional[float]:
    if bid is None or ask is None:
        return None
    if bid <= 0 or ask <= 0:
        return None
    return round((bid + ask) / 2.0, 2)


class AlpacaChainSource(ChainSource):
    """Fetch option chains including greeks using Alpaca market data."""

    def __init__(self) -> None:
        self._client = None
        self._settings = None

    def _get_client(self):  # type: ignore[no-untyped-def]
        if self._client is None:
            settings = get_settings()
            self._settings = settings
            from alpaca.data.historical import OptionHistoricalDataClient

            self._client = OptionHistoricalDataClient(
                settings.alpaca_key_id, settings.alpaca_secret_key
            )
        return self._client

    async def fetch(self, underlying: str) -> List[OptionContract]:
        loop = asyncio.get_running_loop()

        def _call() -> List[OptionContract]:
            client = self._get_client()
            from alpaca.data.requests import OptionChainRequest

            request = OptionChainRequest(symbol=underlying)
            response = client.get_option_chain(request)
            today = _dt.date.today()
            contracts: List[OptionContract] = []
            for option in getattr(response, "options", []) or []:
                expiration = getattr(option, "expiration", None)
                if isinstance(expiration, _dt.date):
                    dte = (expiration - today).days
                    expiry_str = expiration.isoformat()
                elif isinstance(expiration, _dt.datetime):
                    expiration_date = expiration.date()
                    dte = (expiration_date - today).days
                    expiry_str = expiration_date.isoformat()
                else:
                    dte = 0
                    expiry_str = str(expiration)
                greeks = getattr(option, "greeks", None)
                delta = getattr(greeks, "delta", None)
                iv = getattr(greeks, "iv", None)
                bid = getattr(option, "bid", None)
                ask = getattr(option, "ask", None)
                mid = _calculate_mid(bid, ask)
                contracts.append(
                    OptionContract(
                        symbol=getattr(option, "symbol", ""),
                        underlying=underlying,
                        expiry=expiry_str,
                        strike=float(getattr(option, "strike", 0.0) or 0.0),
                        side="call" if getattr(option, "right", "").lower() == "call" else "put",
                        delta=delta,
                        iv=iv,
                        bid=bid,
                        ask=ask,
                        mid=mid,
                        volume=getattr(option, "volume", None),
                        oi=getattr(option, "open_interest", None),
                        dte=int(dte),
                        raw=getattr(option, "__dict__", None),
                    )
                )
            return contracts

        return await loop.run_in_executor(None, _call)
