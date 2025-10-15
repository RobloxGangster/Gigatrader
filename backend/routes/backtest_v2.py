"""API surface for the backtest v2 runner."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.backtest.v2 import BacktestV2Config, run_backtest_v2

router = APIRouter(prefix="/backtest_v2", tags=["backtest_v2"])


class BarPayload(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float
    signal: float
    label: Optional[float] = None
    volume: Optional[float] = None
    position: Optional[float] = None


class BacktestConfigPayload(BaseModel):
    n_splits: int = 3
    purge: int = 0
    embargo: int = 0
    initial_capital: float = 100_000.0
    position_size: float = 1.0
    spread_bps: float = 1.0
    slippage_bps: float = 1.0
    fee_per_unit: float = 0.0
    daily_loss_limit: Optional[float] = None
    max_drawdown_limit: Optional[float] = None
    entry_threshold: float = 0.0
    annualization_factor: float = 252.0

    def to_config(self) -> BacktestV2Config:
        return BacktestV2Config(
            n_splits=self.n_splits,
            purge=self.purge,
            embargo=self.embargo,
            initial_capital=self.initial_capital,
            position_size=self.position_size,
            spread_bps=self.spread_bps,
            slippage_bps=self.slippage_bps,
            fee_per_unit=self.fee_per_unit,
            daily_loss_limit=self.daily_loss_limit,
            max_drawdown_limit=self.max_drawdown_limit,
            entry_threshold=self.entry_threshold,
            annualization_factor=self.annualization_factor,
        )


class BacktestRequest(BaseModel):
    bars: List[BarPayload]
    config: Optional[BacktestConfigPayload] = None


class BacktestResponse(BaseModel):
    config: Dict[str, Any]
    summary: Dict[str, float]
    trades: List[Dict[str, Any]]
    equity_curve: List[Dict[str, Any]]
    artifacts: Dict[str, str]


@router.post("/", response_model=BacktestResponse)
def backtest_v2_route(req: BacktestRequest) -> BacktestResponse:
    if not req.bars:
        raise HTTPException(status_code=400, detail="bars payload cannot be empty")

    rows: List[Dict[str, Any]] = []
    for bar in req.bars:
        if hasattr(bar, "model_dump"):
            rows.append(bar.model_dump())
        else:  # pragma: no cover - pydantic v1 fallback
            rows.append(bar.dict())
    frame = pd.DataFrame(rows)
    config = req.config.to_config() if req.config else BacktestV2Config()
    result = run_backtest_v2(frame, config)
    return BacktestResponse(**result)
