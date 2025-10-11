"""Portfolio state abstractions for risk management."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional
import time


@dataclass(slots=True)
class Position:
    """Lightweight position snapshot."""

    symbol: str
    qty: float
    notional: float
    is_option: bool = False
    metadata: Optional[dict] = None


class StateProvider:
    """Abstraction over live portfolio state.

    Phase 3 TODO: implement with Alpaca Trading API.
    """

    def get_day_pnl(self) -> float:  # pragma: no cover - interface definition
        raise NotImplementedError

    def get_positions(self) -> Dict[str, Position]:  # pragma: no cover - interface definition
        raise NotImplementedError

    def get_portfolio_notional(self) -> float:  # pragma: no cover - interface definition
        raise NotImplementedError

    def get_account_equity(self) -> Optional[float]:  # pragma: no cover - interface definition
        return None


@dataclass
class InMemoryState(StateProvider):
    """Simple in-memory implementation for tests and local dry-runs."""

    day_pnl: float = 0.0
    positions: Dict[str, Position] = field(default_factory=dict)
    portfolio_notional: float = 0.0
    account_equity: Optional[float] = None
    last_trade_ts_by_symbol: Dict[str, float] = field(default_factory=dict)

    def get_day_pnl(self) -> float:
        return self.day_pnl

    def get_positions(self) -> Dict[str, Position]:
        return dict(self.positions)

    def get_portfolio_notional(self) -> float:
        return self.portfolio_notional

    def get_account_equity(self) -> Optional[float]:
        return self.account_equity

    def mark_trade(self, symbol: str, when: Optional[float] = None) -> None:
        self.last_trade_ts_by_symbol[symbol] = when if when is not None else time.time()

    def last_trade_age(self, symbol: str) -> Optional[float]:
        ts = self.last_trade_ts_by_symbol.get(symbol)
        if ts is None:
            return None
        return max(0.0, time.time() - ts)
