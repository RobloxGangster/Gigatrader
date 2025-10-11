"""Gateway responsible for proposing option trades."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from services.execution.engine import ExecutionEngine
from services.execution.types import ExecIntent
from services.options.alpaca_chain import AlpacaChainSource
from services.options.chain import ChainSource
from services.options.select import select_contract
from services.risk.engine import Proposal, RiskManager


def _env_cast(name: str, default: Any) -> Any:
    value = os.getenv(name)
    if value is None:
        return default
    cast_type = type(default)
    try:
        if cast_type is bool:
            return value.strip().lower() in {"1", "true", "yes", "y", "on"}
        return cast_type(value)
    except Exception:
        return default


class OptionGateway:
    """Fetch, validate, and submit option trades using shared infrastructure."""

    def __init__(
        self,
        *,
        exec_engine: ExecutionEngine,
        chain_source: Optional[ChainSource] = None,
        risk_manager: Optional[RiskManager] = None,
    ) -> None:
        self.exec = exec_engine
        self.chain = chain_source or AlpacaChainSource()
        self.risk = risk_manager or getattr(exec_engine, "risk", None)
        if self.risk is None:
            raise ValueError("OptionGateway requires a RiskManager instance")

    async def propose_option_trade(self, underlying: str, side: str, qty: float) -> Dict[str, Any]:
        """Fetch the option chain, select a contract, and submit through the execution engine."""

        target_delta = float(_env_cast("OPTIONS_TARGET_DELTA", 0.30))
        delta_band = float(_env_cast("OPTIONS_DELTA_BAND", 0.05))
        min_oi = int(_env_cast("OPTIONS_MIN_OI", 150))
        min_volume = int(_env_cast("OPTIONS_MIN_VOLUME", 75))
        min_dte = int(_env_cast("OPTIONS_MIN_DTE", 7))
        max_dte = int(_env_cast("OPTIONS_MAX_DTE", 45))
        price_max = float(_env_cast("OPTIONS_PRICE_MAX", 50.0))

        contracts = await self.chain.fetch(underlying)
        option_side = "call" if side.lower() == "buy" else "put"
        selected = select_contract(
            contracts,
            option_side,
            target_delta,
            delta_band,
            min_oi,
            min_volume,
            min_dte,
            max_dte,
            price_max,
        )
        if selected is None:
            return {"accepted": False, "reason": "no_contract_found"}

        proposal = Proposal(
            symbol=underlying,
            side=side,
            qty=qty,
            price=selected.mid or 0.0,
            is_option=True,
            delta=selected.delta,
        )
        decision = self.risk.pre_trade_check(
            proposal,
            symbol_oi=selected.oi,
            symbol_vol=selected.volume,
        )
        if not decision.allow:
            return {"accepted": False, "reason": f"risk_denied:{decision.reason}"}

        intent = ExecIntent(
            symbol=underlying,
            side=side,
            qty=qty,
            limit_price=selected.mid,
            asset_class="option",
            option_symbol=selected.symbol,
            meta={
                "selected": {
                    "symbol": selected.symbol,
                    "delta": selected.delta,
                    "mid": selected.mid,
                    "dte": selected.dte,
                }
            },
        )
        result = await self.exec.submit(intent)
        return {
            "accepted": result.accepted,
            "reason": result.reason,
            "client_order_id": result.client_order_id,
            "selected": selected.symbol,
        }
