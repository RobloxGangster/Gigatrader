"""Application state and data models for the Gigatrader UI."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Mapping, Optional

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_serializer,
    field_validator,
    model_validator,
)


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


class RiskLimits(BaseModelDecimal):
    max_position_pct: float
    max_leverage: float
    max_daily_loss_pct: float


class RiskSnapshot(BaseModelDecimal):
    run_id: str
    daily_loss_pct: float
    max_exposure: float
    open_positions: int
    breached: bool

    profile: str
    equity: float
    cash: float
    exposure_pct: float
    day_pnl: float
    leverage: float
    kill_switch: bool
    limits: RiskLimits
    timestamp: str

    _NUM_FIELDS = [
        "daily_loss_pct",
        "max_exposure",
        "equity",
        "cash",
        "exposure_pct",
        "day_pnl",
        "leverage",
    ]

    @field_validator(*_NUM_FIELDS, mode="before")
    @classmethod
    def _num_to_float(cls, v):
        if isinstance(v, Decimal):
            return float(v)
        return v


class IndicatorPoint(BaseModelDecimal):
    """Flexible indicator point supporting optional metadata."""

    model_config = ConfigDict(extra="allow")

    timestamp: Optional[datetime] = None
    label: Optional[str] = None
    value: Optional[Decimal] = None


class Indicators(BaseModelDecimal):
    symbol: str
    interval: str = "1m"
    indicators: Dict[str, List[IndicatorPoint | Decimal | float | int | None]] = Field(
        default_factory=dict
    )
    has_data: bool = False

    def latest(self, name: str) -> Optional[float]:
        series = self.indicators.get(name) or []
        for item in reversed(series):
            value: Optional[float]
            if isinstance(item, IndicatorPoint):
                value = float(item.value) if item.value is not None else None
            elif isinstance(item, (int, float, Decimal)):
                value = float(item)
            elif isinstance(item, dict):  # pragma: no cover - defensive fallback
                raw = item.get("value")
                value = float(raw) if raw is not None else None
            else:  # pragma: no cover - resilience for unexpected payloads
                value = None
            if value is not None:
                return value
        return None

    def frame(self) -> Optional["pd.DataFrame"]:
        try:
            import pandas as pd  # type: ignore
        except Exception:  # pragma: no cover - optional dependency guard
            return None

        rows: Dict[str, List[Optional[float]]] = {}
        timestamps: List[str] = []

        for name, series in self.indicators.items():
            values: List[Optional[float]] = []
            labels: List[str] = []
            for entry in series:
                if isinstance(entry, IndicatorPoint):
                    value = float(entry.value) if entry.value is not None else None
                    label = entry.label or (
                        entry.timestamp.isoformat() if entry.timestamp else ""
                    )
                elif isinstance(entry, (int, float, Decimal)):
                    value = float(entry)
                    label = ""
                elif isinstance(entry, dict):  # pragma: no cover - defensive fallback
                    raw = entry.get("value")
                    value = float(raw) if raw is not None else None
                    label = entry.get("label") or entry.get("timestamp") or ""
                else:  # pragma: no cover - unexpected payload
                    value = None
                    label = ""
                values.append(value)
                labels.append(label)

            rows[name] = values
            if len(labels) > len(timestamps):
                timestamps = labels

        if not rows:
            return None

        df = pd.DataFrame(rows)
        if timestamps:
            df.index = timestamps + [""] * (len(df.index) - len(timestamps))
        return df


class ChainRow(BaseModelDecimal):
    symbol: Optional[str] = None
    strike: Decimal
    bid: Decimal
    ask: Decimal
    mid: Optional[Decimal] = None
    iv: Optional[Decimal] = None
    delta: Optional[Decimal] = None
    gamma: Optional[Decimal] = None
    theta: Optional[Decimal] = None
    vega: Optional[Decimal] = None
    oi: Optional[int] = None
    volume: Optional[int] = None
    expiry: Optional[datetime] = None
    option_type: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("option_type", "type")
    )
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

    @field_validator("expiry", mode="before")
    @classmethod
    def parse_expiry(cls, v):
        if v in (None, ""):
            return None
        if isinstance(v, datetime):
            return v
        if isinstance(v, date):
            return datetime.combine(v, datetime.min.time())
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v)
            except ValueError:
                return None
        return v


class OptionChain(BaseModelDecimal):
    symbol: Optional[str] = None
    expiry: Optional[datetime] = None
    contracts: List[ChainRow] = Field(default_factory=list)
    rows: List[ChainRow] = Field(default_factory=list)
    reason: Optional[str] = None
    mock: bool = False

    @model_validator(mode="before")
    @classmethod
    def _sync_contracts(cls, values):
        if isinstance(values, dict):
            contracts = values.get("contracts")
            rows = values.get("rows")
            if contracts is None and isinstance(rows, list):
                values["contracts"] = rows
            elif rows is None and isinstance(contracts, list):
                values["rows"] = contracts
        return values

    @model_validator(mode="after")
    def _populate_metadata(self):
        if not self.rows and self.contracts:
            self.rows = list(self.contracts)
        if not self.contracts and self.rows:
            self.contracts = list(self.rows)

        source = self.rows or self.contracts
        if source:
            first = source[0]
            if self.symbol is None and first.symbol is not None:
                self.symbol = first.symbol
            if self.expiry is None and first.expiry is not None:
                self.expiry = first.expiry
        return self


class Greeks(BaseModelDecimal):
    contract: str
    delta: Decimal = Field(default=Decimal("0"))
    gamma: Decimal = Field(default=Decimal("0"))
    theta: Decimal = Field(default=Decimal("0"))
    vega: Decimal = Field(default=Decimal("0"))
    rho: Decimal = Field(default=Decimal("0"))
    updated_at: Optional[datetime] = None
    reason: Optional[str] = None
    mock: bool = False

    @model_validator(mode="before")
    @classmethod
    def _expand_nested(cls, values):
        if isinstance(values, Mapping):
            nested = values.get("greeks")
            if isinstance(nested, Mapping):
                for key in ("delta", "gamma", "theta", "vega", "rho"):
                    values.setdefault(key, nested.get(key))
        return values


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
