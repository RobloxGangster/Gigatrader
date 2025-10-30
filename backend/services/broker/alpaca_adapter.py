"""Alpaca broker adapter used by the backend trading services."""

from __future__ import annotations

import logging
import os
from typing import Any

from alpaca_trade_api import REST as AlpacaREST

from core.config import Settings
from backend.utils.structlog import jlog

log = logging.getLogger(__name__)


class AlpacaBrokerAdapter:
    """Thin wrapper around the Alpaca REST trading client."""

    def __init__(self, settings: Settings):
        profile = settings.profile
        base_url = (
            os.getenv("ALPACA_BASE_URL")
            or (
                "https://paper-api.alpaca.markets"
                if profile == "paper"
                else "https://api.alpaca.markets"
            )
        )
        self._rest = AlpacaREST(
            key_id=os.getenv("ALPACA_KEY_ID"),
            secret_key=os.getenv("ALPACA_SECRET_KEY"),
            base_url=base_url,
        )
        self._settings = settings
        log.info(
            "broker.alpaca.init",
            extra={
                "base_url": base_url,
                "profile": profile,
                "dry_run": settings.dry_run,
                "mock_mode": settings.mock_mode,
            },
        )

    def account(self) -> dict[str, Any]:
        return self._rest.get_account()._raw

    def positions(self) -> list[dict[str, Any]]:
        return [position._raw for position in self._rest.list_positions()]

    def orders(self, status: str = "open", limit: int = 100) -> list[dict[str, Any]]:
        return [order._raw for order in self._rest.list_orders(status=status, limit=limit)]

    def submit_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        *,
        type: str = "market",
        time_in_force: str = "day",
    ) -> dict[str, Any]:
        if self._settings.mock_mode or self._settings.dry_run:
            try:
                jlog(
                    "trade.adapter.block",
                    reason="dry_run" if self._settings.dry_run else "mock_mode",
                    payload={
                        "symbol": symbol,
                        "qty": qty,
                        "side": side,
                        "type": type,
                        "time_in_force": time_in_force,
                    },
                )
            except Exception:  # pragma: no cover - logging guard
                log.debug("failed to emit trade.adapter.block", exc_info=True)
            log.warning(
                "broker.alpaca.dry_run",
                extra={"symbol": symbol, "qty": qty, "side": side},
            )
            return {
                "id": "dry-run",
                "symbol": symbol,
                "qty": qty,
                "side": side,
                "submitted": False,
                "reason": "dry_run_or_mock",
            }
        log.info(
            "broker.alpaca.submit_order",
            extra={
                "symbol": symbol,
                "qty": qty,
                "side": side,
                "type": type,
                "time_in_force": time_in_force,
            },
        )
        try:
            jlog(
                "trade.adapter.request",
                endpoint="alpaca/orders",
                body={
                    "symbol": symbol,
                    "qty": qty,
                    "side": side,
                    "type": type,
                    "time_in_force": time_in_force,
                },
            )
        except Exception:  # pragma: no cover - logging guard
            log.debug("failed to emit trade.adapter.request", exc_info=True)
        order = self._rest.submit_order(
            symbol=symbol,
            qty=qty,
            side=side,
            type=type,
            time_in_force=time_in_force,
        )
        log.info(
            "broker.alpaca.order_submitted",
            extra={"symbol": symbol, "qty": qty, "side": side, "id": order.id},
        )
        data = order._raw
        try:
            jlog(
                "trade.adapter.response",
                status_code=200,
                body=data,
            )
        except Exception:  # pragma: no cover - logging guard
            log.debug("failed to emit trade.adapter.response", exc_info=True)
        return data

