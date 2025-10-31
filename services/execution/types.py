"""Execution intent/result dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional

Side = Literal["buy", "sell"]
AssetClass = Literal["equity", "option"]


@dataclass(slots=True)
class ExecIntent:
    """Normalized order intent produced by upstream strategy/risk layers."""

    symbol: str
    side: Side
    qty: float
    limit_price: Optional[float] = None
    asset_class: AssetClass = "equity"
    client_tag: Optional[str] = None
    take_profit_pct: Optional[float] = None
    stop_loss_pct: Optional[float] = None
    option_symbol: Optional[str] = None
    submit_side: Optional[Side] = None
    meta: Dict[str, Any] = field(default_factory=dict)
    time_in_force: Optional[str] = None
    order_type: Optional[str] = None

    def idempotency_key(self) -> str:
        """Stable key describing the unique semantics of the intent."""

        parts = [
            self.symbol,
            self.side,
            f"{self.qty:.8f}",
            "mkt" if self.limit_price is None else f"{self.limit_price:.8f}",
            self.asset_class,
            self.client_tag or "",
        ]
        if self.time_in_force:
            parts.append(self.time_in_force.lower())
        if self.order_type:
            parts.append(self.order_type.lower())
        if self.option_symbol:
            parts.append(self.option_symbol)
        return "|".join(parts)


@dataclass(slots=True)
class ExecResult:
    """Outcome of attempting to submit an execution intent."""

    accepted: bool
    reason: str
    client_order_id: Optional[str] = None
    order_id: Optional[str] = None
