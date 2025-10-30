from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Side = Literal["buy", "sell"]
OrderType = Literal["market", "limit", "stop", "stop_limit"]
TimeInForce = Literal["day", "gtc", "opg", "ioc", "fok"]


class OrderRequest(BaseModel):
    symbol: str = Field(..., description="Ticker symbol, e.g. AAPL")
    qty: float = Field(..., gt=0, description="Shares quantity")
    side: Side
    type: OrderType
    time_in_force: TimeInForce = "day"
    limit_price: Optional[float] = Field(None, gt=0)
    stop_price: Optional[float] = Field(None, gt=0)
    extended_hours: bool = False
    client_order_id: Optional[str] = None


class OrderResponse(BaseModel):
    id: str
    client_order_id: Optional[str] = None
    symbol: str
    qty: float
    side: Side
    type: OrderType
    time_in_force: TimeInForce
    status: str
    submitted_at: Optional[str] = None
    filled_qty: Optional[float] = None
    filled_avg_price: Optional[float] = None
    raw: Optional[dict] = None
