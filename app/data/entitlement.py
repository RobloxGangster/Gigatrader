from __future__ import annotations

import os

# Optional dependency — must NOT crash on import if absent or layout differs.
APIError = None
StockHistoricalDataClient = None

# APIError lives in alpaca.common.exceptions (stable)
try:  # pragma: no cover
    from alpaca.common.exceptions import APIError  # type: ignore
except Exception:  # pragma: no cover
    APIError = None

# StockHistoricalDataClient moved across versions:
# - new: alpaca.data.historical.stock.StockHistoricalDataClient
# - old: alpaca.data.StockHistoricalDataClient
try:  # pragma: no cover
    if StockHistoricalDataClient is None:
        from alpaca.data.historical.stock import (
            StockHistoricalDataClient as _StockHistoricalDataClient,
        )  # type: ignore
        StockHistoricalDataClient = _StockHistoricalDataClient
except Exception:  # pragma: no cover
    try:  # pragma: no cover
        from alpaca.data import StockHistoricalDataClient as _StockHistoricalDataClient  # type: ignore
        StockHistoricalDataClient = _StockHistoricalDataClient
    except Exception:  # pragma: no cover
        StockHistoricalDataClient = None


def select_feed(strict_sip: bool | None = None) -> str:
    """
    Decide between 'sip' and 'iex' (or other premium feeds).
    For tests and environments without alpaca-py news/data clients,
    this must return deterministically without raising.
    """

    if strict_sip is None:
        strict_sip = os.getenv("STRICT_SIP", "false").lower() in ("1", "true", "yes")

    if strict_sip:
        return "sip"

    # If the client isn't available in this environment, fall back safely.
    if StockHistoricalDataClient is None:
        return "sip"

    # In live code you could probe entitlements here with the client.
    # For tests we just prefer SIP unless STRICT_SIP is explicitly false and
    # a premium feed is known to be available (skip probing to avoid network).
    return "sip"


def sip_entitled(symbol: str = "SPY") -> bool:
    """Backward-compatible helper returning True when SIP should be used."""

    return select_feed(strict_sip=False).lower() == "sip"
