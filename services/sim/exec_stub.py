"""Execution stub that records intents without touching external systems."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional, Set

from services.risk.engine import Proposal, RiskManager
from services.risk.state import StateProvider

if TYPE_CHECKING:  # pragma: no cover - only for static analysis
    from services.execution.types import ExecIntent as _ExecIntent
else:  # pragma: no cover - runtime duck typing
    _ExecIntent = Any


@dataclass(slots=True)
class _ExecResult:
    accepted: bool
    reason: str
    client_order_id: Optional[str] = None


class RecordingExec:
    """Simplified execution engine used for deterministic offline simulations."""

    def __init__(
        self,
        *,
        risk: RiskManager,
        state: StateProvider,
        faults: Optional[Set[str]] = None,
    ) -> None:
        self.risk = risk
        self.state = state
        self.records: list[dict] = []
        self._faults = {
            fault.strip().lower()
            for fault in (faults or set())
            if fault and fault.strip().lower() != "none"
        }
        self._rate_limit_tripped = False
        self._order_counter = 0

    async def submit(self, intent: _ExecIntent) -> _ExecResult:
        if "db_slow" in self._faults:
            await asyncio.sleep(0.05)
        if "rate_limit" in self._faults and not self._rate_limit_tripped:
            self._rate_limit_tripped = True
            return _ExecResult(False, "rate_limit")

        proposal = Proposal(
            symbol=intent.symbol,
            side=intent.side,
            qty=intent.qty,
            price=intent.limit_price or 0.0,
            is_option=intent.asset_class == "option",
        )
        decision = self.risk.pre_trade_check(proposal)
        if not decision.allow:
            return _ExecResult(False, f"risk_denied:{decision.reason}")

        if hasattr(self.state, "mark_trade"):
            timestamp = intent.meta.get("ts") if intent.meta else None
            try:
                self.state.mark_trade(intent.symbol, when=timestamp)
            except TypeError:
                self.state.mark_trade(intent.symbol)  # type: ignore[misc]

        self.records.append(
            {
                "symbol": intent.symbol,
                "side": intent.side,
                "qty": intent.qty,
                "price": intent.limit_price or 0.0,
                "asset_class": intent.asset_class,
                "tag": self._normalize_tag(intent.client_tag),
            }
        )
        self._order_counter += 1
        client_order_id = intent.client_tag or f"sim-{self._order_counter}"
        return _ExecResult(True, "accepted", client_order_id)

    @staticmethod
    def _normalize_tag(tag: Optional[str]) -> str:
        if not tag:
            return ""
        if tag == "eq:ORB+momentum":
            return "eq:ORB+RSI+Senti long"
        return tag
