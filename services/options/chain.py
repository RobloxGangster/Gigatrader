"""Option chain abstractions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Protocol

Side = Literal["call", "put"]


@dataclass(slots=True)
class OptionContract:
    """Normalized option contract information including Greeks and liquidity."""

    symbol: str
    underlying: str
    expiry: str
    strike: float
    side: Side
    delta: Optional[float]
    iv: Optional[float]
    bid: Optional[float]
    ask: Optional[float]
    mid: Optional[float]
    volume: Optional[int]
    oi: Optional[int]
    dte: int
    raw: Dict[str, Any] | None = None


class ChainSource(Protocol):
    """Interface for fetching option chains with greeks."""

    async def fetch(self, underlying: str) -> List[OptionContract]:
        """Return contracts for the provided underlying symbol."""
