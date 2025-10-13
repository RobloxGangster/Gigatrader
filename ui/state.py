"""Application state and data models for the Gigatrader UI."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_serializer, field_validator


class BaseModelDecimal(BaseModel):
    """Base model ensuring Decimals are kept during json serialization."""

    model_config = ConfigDict(arbitrary_types_allowed=True, from_attributes=True)

    @field_serializer("*", when_used="json")
    def _serialize_decimal(cls, value):
        if isinstance(value, Decimal):
            return str(value)
        return value


class OrderStatus(str, Enum):
    PENDING = "pending"
    WORKING = "working"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class Order(BaseModelDecimal):
    order_id: str
    symbol: str
    side: str
    qty: Decimal
    filled_qty: Decimal
    leaves_qty: Decimal
    tif: str
    status: OrderStatus
    avg_price: Optional[Decimal] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class Position(BaseModelDecimal):
    symbol: str
    qty: Decimal
    avg_price: Decimal
    unrealized: Decimal
    realized: Decimal
    leverage: Decimal
    delta: Optional[Decimal] = None
    gamma: Optional[Decimal] = None
    theta: Optional[Decimal] = None
    vega: Optional[Decimal] = None


class Trade(BaseModelDecimal):
    trade_id: str
    timestamp: datetime
    symbol: str
    side: str
    qty: Decimal
    price: Decimal
    pnl: Decimal
    reason: str
    strategy: str
    outcome: str


class EquityPoint(BaseModelDecimal):
    timestamp: datetime
    equity: Decimal
    drawdown: Decimal
    exposure: Decimal


class RiskSnapshot(BaseModelDecimal):
    run_id: Optional[str]
    daily_loss_pct: Decimal
    max_exposure: Decimal
    open_positions: int
    leverage: Decimal
    breached: Dict[str, Decimal]


class IndicatorSeries(BaseModelDecimal):
    label: str
    value: Decimal
    trend: Optional[str] = None


class Indicators(BaseModelDecimal):
    symbol: str
    atr: Decimal
    rsi: Decimal
    z_score: Decimal
    orb: Decimal
    updated_at: datetime
    series: List[IndicatorSeries] = Field(default_factory=list)


class ChainRow(BaseModelDecimal):
    strike: Decimal
    bid: Decimal
    ask: Decimal
    mid: Decimal
    iv: Decimal
    delta: Decimal
    gamma: Decimal
    theta: Decimal
    vega: Decimal
    oi: int
    volume: int
    expiry: datetime
    option_type: str
    is_liquid: bool = True

    @field_validator("mid", mode="before")
    @classmethod
    def default_mid(cls, v, info: ValidationInfo):
        if v is not None:
            return v
        data = getattr(info, "data", {}) or {}
        bid = data.get("bid")
        ask = data.get("ask")
        if bid is None or ask is None:
            return Decimal("0")
        return (Decimal(str(bid)) + Decimal(str(ask))) / Decimal("2")


class OptionChain(BaseModelDecimal):
    symbol: str
    expiry: datetime
    rows: List[ChainRow]


class Greeks(BaseModelDecimal):
    contract: str
    delta: Decimal
    gamma: Decimal
    theta: Decimal
    vega: Decimal
    rho: Decimal
    updated_at: datetime


class LogEvent(BaseModelDecimal):
    timestamp: datetime
    level: str
    component: str
    message: str
    trace_id: str
    correlation_id: Optional[str] = None


class PacingStats(BaseModelDecimal):
    rpm: Decimal
    backoff_events: int
    retries: int
    max_rpm: Decimal
    window_seconds: int
    history: List[Decimal]


class RunInfo(BaseModelDecimal):
    run_id: str
    started_at: datetime
    ended_at: Optional[datetime]
    preset: str
    profile: str


class ReportSummary(BaseModelDecimal):
    run_id: str
    sharpe: Decimal
    sortino: Decimal
    max_drawdown: Decimal
    win_rate: Decimal
    turnover: Decimal
    equity_curve: List[EquityPoint]


class AppSessionState(BaseModel):
    """Container for session level state persisted across reruns."""

    profile: str = "paper"
    run_id: Optional[str] = None
    selected_symbol: str = "AAPL"
    option_expiry: Optional[str] = None
    filters: Dict[str, str] = Field(default_factory=dict)
    column_filters: Dict[str, Dict[str, str]] = Field(default_factory=dict)
    last_trace_id: Optional[str] = None
    strategy_params: Dict[str, float] = Field(default_factory=dict)

    model_config = ConfigDict(arbitrary_types_allowed=True, from_attributes=True)


def init_session_state() -> AppSessionState:
    """Initialise Streamlit session state if missing."""
    import streamlit as st

    if "app_state" not in st.session_state:
        st.session_state["app_state"] = AppSessionState()
    return st.session_state["app_state"]


def update_session_state(**kwargs: object) -> None:
    """Update the stored session state with provided keyword arguments."""
    import streamlit as st

    state: AppSessionState = st.session_state.setdefault("app_state", AppSessionState())
    for key, value in kwargs.items():
        if hasattr(state, key):
            setattr(state, key, value)
