from __future__ import annotations

from typing import Any, Dict, List

from alpaca.trading.enums import QueryOrderStatus
from alpaca.trading.requests import GetOrdersRequest

from core.broker_config import is_mock

from .alpaca_client import get_trading_client


def pull_orders() -> List[Dict[str, Any]]:
    tc = get_trading_client()
    orders = tc.get_orders(GetOrdersRequest(status=QueryOrderStatus.ALL))
    out: List[Dict[str, Any]] = []
    for o in orders:
        out.append(o.__dict__.get("_raw", {}))
    return out


def pull_positions() -> List[Dict[str, Any]]:
    tc = get_trading_client()
    positions = tc.get_all_positions()
    return [p.__dict__.get("_raw", {}) for p in positions]


def pull_account() -> Dict[str, Any]:
    tc = get_trading_client()
    acc = tc.get_account()
    return acc.__dict__.get("_raw", {})


# no-op stubs if MOCK
def pull_all_if_live() -> Dict[str, Any]:
    if is_mock():
        return {"mode": "mock", "orders": [], "positions": [], "account": {}}
    return {
        "mode": "paper",
        "orders": pull_orders(),
        "positions": pull_positions(),
        "account": pull_account(),
    }
