from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from functools import partial
from typing import Any, Dict, Optional

from backend.config.extended_universe import is_extended

from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import (
    LimitOrderRequest,
    MarketOrderRequest,
    StopLimitOrderRequest,
    StopOrderRequest,
)


class AlpacaBrokerAdapter:
    """Thin async wrapper around the Alpaca trading client."""

    def __init__(self, key_id: str, secret_key: str, *, paper: bool = True) -> None:
        self.client = TradingClient(key_id, secret_key, paper=paper)

    async def get_clock(self) -> Dict[str, Any]:
        """Return the Alpaca trading clock with normalised timestamps."""

        loop = asyncio.get_running_loop()
        clock = await loop.run_in_executor(None, self.client.get_clock)

        def _as_iso(value: Optional[Any]) -> Optional[str]:
            if value is None:
                return None
            if isinstance(value, datetime):
                if value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc)
                return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            if hasattr(value, "isoformat"):
                try:
                    raw = value.isoformat()  # type: ignore[call-arg]
                    return raw.replace("+00:00", "Z")
                except Exception:  # pragma: no cover - defensive conversion
                    return None
            return str(value)

        return {
            "is_open": bool(getattr(clock, "is_open", False)),
            "next_open": _as_iso(getattr(clock, "next_open", None)),
            "next_close": _as_iso(getattr(clock, "next_close", None)),
            "timestamp": _as_iso(getattr(clock, "timestamp", None)),
        }

    async def place_order(
        self,
        *,
        symbol: str,
        qty: float,
        side: str,
        type: str,
        time_in_force: str = "day",
        limit_price: float | None = None,
        stop_price: float | None = None,
        extended_hours: bool = False,
        client_order_id: str | None = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if is_extended():
            extended_hours = True
            if type.lower() != "limit":
                raise ValueError("Extended-hours requires type='limit'")
            if time_in_force.lower() != "day":
                raise ValueError("Extended-hours requires time_in_force='day'")
        side_lower = side.lower()
        if side_lower not in {"buy", "sell"}:
            raise ValueError(f"Unsupported order side: {side}")
        side_enum = OrderSide.BUY if side_lower == "buy" else OrderSide.SELL

        try:
            tif_enum = TimeInForce[time_in_force.upper()]
        except KeyError as exc:
            raise ValueError(f"Unsupported time_in_force: {time_in_force}") from exc

        order_type = type.lower()
        if order_type == "market":
            request = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=side_enum,
                time_in_force=tif_enum,
                extended_hours=extended_hours,
                client_order_id=client_order_id,
            )
        elif order_type == "limit":
            if limit_price is None:
                raise ValueError("limit_price is required for limit orders")
            request = LimitOrderRequest(
                symbol=symbol,
                qty=qty,
                side=side_enum,
                time_in_force=tif_enum,
                limit_price=limit_price,
                extended_hours=extended_hours,
                client_order_id=client_order_id,
            )
        elif order_type == "stop":
            if stop_price is None:
                raise ValueError("stop_price is required for stop orders")
            request = StopOrderRequest(
                symbol=symbol,
                qty=qty,
                side=side_enum,
                time_in_force=tif_enum,
                stop_price=stop_price,
                extended_hours=extended_hours,
                client_order_id=client_order_id,
            )
        elif order_type == "stop_limit":
            if stop_price is None or limit_price is None:
                raise ValueError(
                    "stop_price and limit_price are required for stop_limit orders"
                )
            request = StopLimitOrderRequest(
                symbol=symbol,
                qty=qty,
                side=side_enum,
                time_in_force=tif_enum,
                stop_price=stop_price,
                limit_price=limit_price,
                extended_hours=extended_hours,
                client_order_id=client_order_id,
            )
        else:
            raise ValueError(f"Unsupported order type: {type}")

        submit = partial(self.client.submit_order, order_data=request)
        try:
            order = await asyncio.get_running_loop().run_in_executor(None, submit)
        except APIError as exc:  # pragma: no cover - network interaction
            detail: str | None = None
            try:
                detail = exc.message  # type: ignore[attr-defined]
            except Exception:
                detail = None
            raise RuntimeError(detail or str(exc)) from exc
        except Exception:
            raise

        raw: Dict[str, Any]
        if hasattr(order, "model_dump"):
            raw = order.model_dump(mode="json")  # type: ignore[call-arg]
        elif hasattr(order, "__dict__"):
            raw = dict(order.__dict__)
        else:  # pragma: no cover - defensive
            raw = {}

        submitted_at = getattr(order, "submitted_at", None)
        if submitted_at is not None:
            submitted_at = getattr(submitted_at, "isoformat", lambda: submitted_at)()

        filled_qty = getattr(order, "filled_qty", None)
        filled_avg_price = getattr(order, "filled_avg_price", None)

        def _to_float(value: Any) -> float | None:
            if value is None:
                return None
            try:
                return float(value)
            except Exception:  # pragma: no cover - defensive conversion
                return None

        return {
            "id": str(getattr(order, "id", getattr(order, "order_id", ""))),
            "client_order_id": getattr(order, "client_order_id", None),
            "symbol": getattr(order, "symbol", symbol),
            "qty": _to_float(getattr(order, "qty", qty)) or float(qty),
            "side": str(
                getattr(getattr(order, "side", side_enum), "value", side_lower)
            ).lower(),
            "type": str(
                getattr(getattr(order, "type", order_type), "value", order_type)
            ).lower(),
            "time_in_force": str(
                getattr(getattr(order, "time_in_force", tif_enum), "value", time_in_force)
            ).lower(),
            "status": str(
                getattr(getattr(order, "status", "accepted"), "value", None)
                or getattr(order, "status", "accepted")
            ).lower(),
            "submitted_at": submitted_at,
            "filled_qty": _to_float(filled_qty),
            "filled_avg_price": _to_float(filled_avg_price),
            "raw": raw,
        }
