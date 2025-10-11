"""Data loading helpers for the offline simulator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterator, Set
import csv
import json


@dataclass(slots=True)
class BarRow:
    """Structured representation of an OHLCV row from the CSV fixture."""

    ts: float
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float


def load_bars(csv_path: str, symbols: Set[str], max_rows: int) -> Iterator[BarRow]:
    """Yield normalized bar rows filtered by the requested symbol universe."""

    normalized_symbols = {sym.upper() for sym in symbols}
    yielded = 0
    with open(csv_path, "r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if yielded >= max_rows:
                break
            symbol = (row.get("symbol") or "").upper()
            if symbol not in normalized_symbols:
                continue
            yielded += 1
            yield BarRow(
                ts=float(row.get("ts", 0.0)),
                symbol=symbol,
                open=float(row.get("open", 0.0)),
                high=float(row.get("high", 0.0)),
                low=float(row.get("low", 0.0)),
                close=float(row.get("close", 0.0)),
                volume=float(row.get("volume", 0.0)),
            )


def load_sentiment(ndjson_path: str) -> Dict[str, float]:
    """Return the latest sentiment score per symbol from a newline-delimited JSON file."""

    scores: Dict[str, float] = {}
    try:
        with open(ndjson_path, "r", encoding="utf-8") as handle:
            for line in handle:
                payload = line.strip()
                if not payload:
                    continue
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                symbol = (obj.get("symbol") or "").upper()
                if not symbol:
                    continue
                score_raw = obj.get("score", 0.0)
                try:
                    score = float(score_raw)
                except (TypeError, ValueError):
                    score = 0.0
                scores[symbol] = score
    except FileNotFoundError:
        return {}
    return scores
