from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from services.market.indicators import OpeningRange, RollingATR, RollingRSI, RollingZScore

logger = logging.getLogger(__name__)


class IndicatorsNotReadyError(RuntimeError):
    """Raised when indicators cannot be produced due to missing market data."""


def build_empty_indicators(symbol: str, interval: str = "1m") -> Dict[str, Any]:
    """Return a canonical empty indicator payload."""

    return {
        "symbol": symbol.upper(),
        "interval": interval,
        "indicators": {},
        "has_data": False,
    }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _fixtures_path() -> Path:
    return _repo_root() / "fixtures"


def _load_bars(symbol: str) -> List[Dict[str, Any]]:
    path = _fixtures_path() / f"bars_{symbol}.csv"
    if not path.exists():
        raise IndicatorsNotReadyError("no bars available")

    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                rows.append(
                    {
                        "timestamp": datetime.fromisoformat(row["time"]),
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": float(row.get("volume", 0.0) or 0.0),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - defensive parsing guard
                logger.debug("indicators.csv.parse_error", extra={"symbol": symbol, "error": str(exc)})
    if not rows:
        raise IndicatorsNotReadyError("empty bars file")
    return rows


def _ema(series: Iterable[float], period: int) -> List[float]:
    alpha = 2.0 / (period + 1)
    ema_values: List[float] = []
    ema: Optional[float] = None
    for value in series:
        if ema is None:
            ema = value
        else:
            ema = (value - ema) * alpha + ema
        ema_values.append(ema)
    return ema_values


def _point(timestamp: datetime, value: Optional[float], **meta: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"timestamp": timestamp.isoformat()}
    if value is not None:
        payload["value"] = value
    if meta:
        payload.update(meta)
    return payload


def load_indicator_snapshot(symbol: str, lookback: int, interval: str = "1m") -> Dict[str, Any]:
    """Load indicator series for a symbol.

    The reference implementation loads synthetic bars from ``fixtures`` to provide
    deterministic data in offline/test environments.  In live deployments this
    function can be replaced with one that queries the production data store.
    """

    if lookback <= 0:
        raise ValueError("lookback must be positive")

    normalized_symbol = symbol.upper()
    rows = _load_bars(normalized_symbol)
    window = rows[-lookback:]

    rsi_calc = RollingRSI()
    atr_calc = RollingATR()
    zscore_calc = RollingZScore()
    orb_calc = OpeningRange()

    closes = [row["close"] for row in window]
    ema20_values = _ema(closes, 20)
    ema50_values = _ema(closes, 50)

    indicators: Dict[str, List[Dict[str, Any]]] = {
        "rsi": [],
        "atr": [],
        "zscore": [],
        "ema_20": [],
        "ema_50": [],
        "orb_breakout": [],
    }

    has_data = False
    for idx, row in enumerate(window):
        timestamp = row["timestamp"]
        close = row["close"]
        high = row["high"]
        low = row["low"]

        rsi = rsi_calc.update(close)
        atr = atr_calc.update(high, low, close)
        zscore = zscore_calc.update(close)
        orb_state = orb_calc.update(high, low)
        breakout = orb_calc.breakout(close)

        ema20 = ema20_values[idx]
        ema50 = ema50_values[idx]

        indicators["rsi"].append(_point(timestamp, rsi))
        indicators["atr"].append(_point(timestamp, atr))
        indicators["zscore"].append(_point(timestamp, zscore))
        indicators["ema_20"].append(_point(timestamp, ema20))
        indicators["ema_50"].append(_point(timestamp, ema50))
        indicators["orb_breakout"].append(_point(timestamp, float(breakout), **orb_state))

        if not has_data and any(value is not None for value in (rsi, atr, zscore)):
            has_data = True

    if not has_data:
        raise IndicatorsNotReadyError("indicators warming up")

    payload = {
        "symbol": normalized_symbol,
        "interval": interval,
        "indicators": indicators,
        "has_data": True,
    }
    return payload


__all__ = [
    "IndicatorsNotReadyError",
    "build_empty_indicators",
    "load_indicator_snapshot",
]
