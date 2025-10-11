"""Shared data structures for the strategy layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class Bar:
    """Lightweight OHLCV container passed into strategies."""

    ts: float
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(slots=True)
class OrderPlan:
    """Normalized trade plan emitted by individual strategies."""

    symbol: str
    side: str  # "buy" | "sell"
    qty: float
    limit_price: Optional[float] = None
    asset_class: str = "equity"  # "equity" or "option"
    note: str = ""
    take_profit_pct: Optional[float] = None
    stop_loss_pct: Optional[float] = None
    option_symbol: Optional[str] = None
