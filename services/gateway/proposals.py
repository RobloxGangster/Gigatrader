"""Gateway for submitting order proposals through the risk engine."""

from __future__ import annotations

from services.risk.engine import Decision, Proposal, RiskManager


class Gateway:
    """Facade that gates order proposals via the risk manager."""

    def __init__(self, risk: RiskManager) -> None:
        self.risk = risk

    def propose_order(self, proposal: Proposal, **symbol_meta) -> Decision:
        """Submit an order proposal after running risk checks."""

        return self.risk.pre_trade_check(proposal, **symbol_meta)
