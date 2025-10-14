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
    from alpaca.trading.enums import AssetClass, OrderSide, QueryOrderStatus, TimeInForce
    from alpaca.trading.models import Order
    from alpaca.trading.requests import (
        GetOrdersRequest,
        LimitOrderRequest,
        StopLossRequest,
        TakeProfitRequest,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - easier local testing without alpaca
    raise RuntimeError("alpaca-py must be installed to use AlpacaAdapter") from exc

from core.config import (
    get_alpaca_settings,
    get_order_defaults,
    alpaca_config_ok,
    masked_tail,
    debug_alpaca_snapshot,
    resolved_env_sources,
)

log = logging.getLogger(__name__)


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
        if not alpaca_config_ok():
            snap = debug_alpaca_snapshot()
            envp = resolved_env_sources()
            log.warning(
                "alpaca adapter unavailable: credentials missing; broker calls disabled | "
                "configured=%s base_url=%s key_tail=%s env=%s",
                snap.get("configured"),
                snap.get("base_url"),
                snap.get("key_tail"),
                envp,
            )
            raise RuntimeError("alpaca_unconfigured")

        cfg = get_alpaca_settings()
        self.client = TradingClient(
            api_key=cfg.api_key_id,
            secret_key=cfg.api_secret_key,
            paper=cfg.paper,
            url=cfg.base_url,
        )
        log.info("alpaca adapter configured base=%s key_tail=%s", cfg.base_url, masked_tail(cfg.api_key_id))
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
            raise RuntimeError("alpaca_unconfigured")

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
                if code == 401:
                    log.error(
                        "alpaca unauthorized; check ALPACA_API_KEY_ID/ALPACA_API_SECRET_KEY/APCA_API_BASE_URL",
                        extra={"client_order_id": cid},
                    )
                    raise

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
            raise RuntimeError("alpaca_unconfigured")
        req = GetOrdersRequest(status=QueryOrderStatus.OPEN, nested=True, limit=500)
        try:
            return list(self.client.get_orders(filter=req))
        except APIError as exc:
            # If unauthorized, bubble a clean hint and let caller decide (recon will back off)
            if getattr(exc, "status_code", None) == 401:
                raise RuntimeError("alpaca_unauthorized") from exc
            raise

    def get_positions(self) -> list[Any]:
        """Return the list of positions from Alpaca."""

        if self.client is None:
            raise RuntimeError("alpaca_unconfigured")
        return list(self.client.get_all_positions())

    def get_account(self):  # noqa: D401 - fastapi serialises the dataclass/dict
        """Return the Alpaca account snapshot."""

        if self.client is None:
            raise RuntimeError("alpaca_unconfigured")
        return self.client.get_account()
