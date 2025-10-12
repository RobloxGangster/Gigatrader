"""Core interfaces defining contracts for the trading platform."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Iterable, List, Optional, Protocol


@dataclass(slots=True)
class Decision:
    """Represents a risk decision for a proposed order."""

    allow: bool
    reason: Optional[str] = None


class DataProvider(ABC):
    """Interface for retrieving and streaming market data."""

    @abstractmethod
    async def get_bars(self, symbol: str, timeframe: str) -> Iterable[dict]:
        """Return historical bar data for ``symbol`` and ``timeframe``."""

    @abstractmethod
    async def get_snapshot(self, symbol: str) -> dict:
        """Return the latest quote/trade snapshot for ``symbol``."""

    @abstractmethod
    def stream_quotes(self, symbols: List[str]) -> AsyncIterator[dict]:
        """Stream quote updates for ``symbols``."""

    @abstractmethod
    def stream_trades(self, symbols: List[str]) -> AsyncIterator[dict]:
        """Stream trade updates for ``symbols``."""

    @abstractmethod
    def stream_bars(self, symbols: List[str], timeframe: str) -> AsyncIterator[dict]:
        """Stream aggregate bar updates."""

    @abstractmethod
    async def get_option_chain(self, underlier: str, expiry: str) -> dict:
        """Return the option chain for ``underlier`` at ``expiry``."""

    @abstractmethod
    async def get_option_greeks(self, contract: str) -> dict:
        """Return greeks for ``contract``."""


class Broker(ABC):
    """Interface for sending orders to the broker."""

    @abstractmethod
    async def submit(self, order: dict) -> dict:
        """Submit a new order and return broker response."""

    @abstractmethod
    async def cancel(self, order_id: str) -> None:
        """Cancel the order identified by ``order_id``."""

    @abstractmethod
    async def replace(self, order_id: str, order: dict) -> dict:
        """Modify an existing order."""

    @abstractmethod
    async def positions(self) -> List[dict]:
        """Fetch current open positions."""

    @abstractmethod
    async def account(self) -> dict:
        """Fetch account information."""

    @abstractmethod
    async def clock(self) -> dict:
        """Return market clock status."""

    @abstractmethod
    async def flatten_all(self) -> None:
        """Close all open positions and cancel outstanding orders."""


class Strategy(ABC):
    """Interface for trading strategies."""

    @abstractmethod
    async def prepare(self, data_context: dict) -> None:
        """Prepare the strategy with any required data."""

    @abstractmethod
    async def on_bar(self, event: dict) -> List[dict]:
        """Process a bar event and return proposed orders."""

    @abstractmethod
    async def on_fill(self, event: dict) -> None:
        """Handle fill events for bookkeeping."""


class RiskManager(ABC):
    """Interface for risk checks applied to proposed orders."""

    @abstractmethod
    async def pre_trade_check(self, order: dict, portfolio: dict) -> Decision:
        """Determine whether ``order`` is allowed given ``portfolio``."""

    @abstractmethod
    async def size(self, order_context: dict) -> float:
        """Return a position size for ``order_context``."""


class SlippageCostModel(Protocol):
    """Protocol describing cost model hooks."""

    def commission(self, order: dict) -> float:
        """Return expected commission for ``order``."""

    def slip(self, order: dict, market_state: dict) -> float:
        """Return expected slippage for ``order``."""
