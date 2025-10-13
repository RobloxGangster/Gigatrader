"""Unified Alpaca Trading API adapter with retries and idempotent helpers."""

from __future__ import annotations

import logging
import time
import uuid
from decimal import Decimal
from typing import Any, Optional

try:  # pragma: no cover - exercised when alpaca-py is optional
    from alpaca.common.exceptions import APIError
    from alpaca.trading.client import TradingClient
    from alpaca.trading.enums import AssetClass, OrderSide, TimeInForce
    from alpaca.trading.models import Order
    from alpaca.trading.requests import LimitOrderRequest, StopLossRequest, TakeProfitRequest
except ModuleNotFoundError as exc:  # pragma: no cover - easier local testing without alpaca
    raise RuntimeError("alpaca-py must be installed to use AlpacaAdapter") from exc

from core.config import get_alpaca_settings, get_order_defaults

log = logging.getLogger("alpaca")


def _to_float(value: Any) -> Any:
    """Convert ``Decimal`` or numeric-ish values into ``float`` for Alpaca SDK."""

    if value is None:
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return value
    return value


class AlpacaAdapter:
    """Thin wrapper around ``TradingClient`` with retry/backoff semantics."""

    def __init__(self) -> None:
        cfg = get_alpaca_settings()
        client_kwargs = {
            "api_key": cfg.api_key_id or None,
            "secret_key": cfg.api_secret_key or None,
            "paper": cfg.paper,
        }
        if cfg.base_url:
            client_kwargs["url_override"] = cfg.base_url

        if not client_kwargs["api_key"] or not client_kwargs["secret_key"]:
            log.warning("alpaca adapter initialised without credentials; broker calls disabled")
            self.client = None
        else:
            self.client = TradingClient(**client_kwargs)
        self.timeout = cfg.request_timeout_s
        self.max_retries = cfg.max_retries
        self.backoff = cfg.retry_backoff_s

    def _backoff(self, attempt: int) -> None:
        sleep_s = min(4.0, self.backoff * (2**attempt))
        log.debug("alpaca.retry sleeping %.2fs (attempt=%s)", sleep_s, attempt)
        time.sleep(sleep_s)

    def place_limit_bracket(
        self,
        *,
        symbol: str,
        side: str,
        qty: int,
        limit_price: float,
        client_order_id: Optional[str] = None,
        tp_pct: Optional[float] = None,
        sl_pct: Optional[float] = None,
        tif: Optional[str] = None,
    ) -> Order:
        defaults = get_order_defaults()
        tif_value = (tif or defaults.tif).upper()
        allow_brackets = defaults.allow_brackets

        if self.client is None:
            raise RuntimeError("Alpaca client not configured")

        side_enum = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
        tif_enum = TimeInForce.GTC if tif_value == "GTC" else TimeInForce.DAY

        cid = client_order_id or f"gt-{uuid.uuid4().hex[:20]}"

        take_profit = None
        stop_loss = None
        if allow_brackets and tp_pct is not None and sl_pct is not None:
            if side_enum == OrderSide.BUY:
                tp_price = limit_price * (1 + tp_pct)
                sl_price = limit_price * (1 - sl_pct)
            else:
                tp_price = limit_price * (1 - tp_pct)
                sl_price = limit_price * (1 + sl_pct)
            take_profit = TakeProfitRequest(limit_price=round(_to_float(tp_price), 4))
            stop_loss = StopLossRequest(stop_price=round(_to_float(sl_price), 4))

        request = LimitOrderRequest(
            symbol=symbol.upper(),
            qty=int(qty),
            side=side_enum,
            time_in_force=tif_enum,
            limit_price=round(_to_float(limit_price), 4),
            client_order_id=cid,
            take_profit=take_profit,
            stop_loss=stop_loss,
            asset_class=AssetClass.US_EQUITY,
        )

        attempt = 0
        while True:
            try:
                order = self.client.submit_order(order_data=request)
                log.info(
                    "alpaca.submit_order ok", extra={"client_order_id": cid, "order_id": getattr(order, "id", None)}
                )
                return order
            except APIError as exc:
                code = getattr(exc, "status_code", None)
                msg = str(exc)
                log.warning(
                    "alpaca.submit_order apierror", extra={"client_order_id": cid, "status_code": code, "error": msg}
                )
                if code in {429, 408, 500, 502, 503, 504} and attempt < self.max_retries:
                    attempt += 1
                    self._backoff(attempt)
                    continue
                raise
            except Exception as exc:  # noqa: BLE001 - bubble unexpected errors after retries
                log.exception(
                    "alpaca.submit_order error", extra={"client_order_id": cid, "error": str(exc)}
                )
                if attempt < self.max_retries:
                    attempt += 1
                    self._backoff(attempt)
                    continue
                raise

    def get_open_orders(self) -> list[Order]:
        """Return the list of open orders from Alpaca."""

        if self.client is None:
            raise RuntimeError("Alpaca client not configured")
        return list(self.client.get_orders(status="open", nested=True, limit=500))

    def get_positions(self) -> list[Any]:
        """Return the list of positions from Alpaca."""

        if self.client is None:
            raise RuntimeError("Alpaca client not configured")
        return list(self.client.get_all_positions())

    def get_account(self):  # noqa: D401 - fastapi serialises the dataclass/dict
        """Return the Alpaca account snapshot."""

        if self.client is None:
            raise RuntimeError("Alpaca client not configured")
        return self.client.get_account()
