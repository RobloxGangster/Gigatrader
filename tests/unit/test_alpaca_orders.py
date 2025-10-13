from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _StubClient:
    response: dict

    def __post_init__(self) -> None:
        self.calls: list[object] = []

    def submit_order(self, *, order_data):
        self.calls.append(order_data)
        return self.response


def _install_alpaca_stubs() -> None:
    """Install minimal alpaca stubs if the real SDK is unavailable."""

    import sys
    import types

    if "alpaca" in sys.modules:
        return

    alpaca_pkg = types.ModuleType("alpaca")
    trading_pkg = types.ModuleType("alpaca.trading")
    client_mod = types.ModuleType("alpaca.trading.client")
    requests_mod = types.ModuleType("alpaca.trading.requests")
    enums_mod = types.ModuleType("alpaca.trading.enums")
    common_pkg = types.ModuleType("alpaca.common")
    exceptions_mod = types.ModuleType("alpaca.common.exceptions")

    class TradingClient:  # pragma: no cover - simple stub
        def submit_order(self, *, order_data):
            return {"stub": order_data}

    class _Request:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class _Enum(str):
        def __new__(cls, value: str):
            return str.__new__(cls, value)

    class APIError(Exception):
        pass

    client_mod.TradingClient = TradingClient
    requests_mod.MarketOrderRequest = _Request
    requests_mod.LimitOrderRequest = _Request
    requests_mod.TakeProfitRequest = _Request
    requests_mod.StopLossRequest = _Request
    enums_mod.OrderSide = _Enum
    enums_mod.TimeInForce = _Enum
    enums_mod.OrderClass = types.SimpleNamespace(BRACKET="BRACKET")
    exceptions_mod.APIError = APIError

    sys.modules["alpaca"] = alpaca_pkg
    sys.modules["alpaca.trading"] = trading_pkg
    sys.modules["alpaca.trading.client"] = client_mod
    sys.modules["alpaca.trading.requests"] = requests_mod
    sys.modules["alpaca.trading.enums"] = enums_mod
    sys.modules["alpaca.common"] = common_pkg
    sys.modules["alpaca.common.exceptions"] = exceptions_mod


_install_alpaca_stubs()

from app.execution.alpaca_orders import submit_order_async, submit_order_sync  # noqa: E402


def test_submit_order_sync_forwards_to_client() -> None:
    client = _StubClient(response={"id": "sync"})
    order_req = object()

    result = submit_order_sync(client, order_req)

    assert client.calls == [order_req]
    assert result == {"id": "sync"}


def test_submit_order_async_runs_in_executor() -> None:
    import asyncio

    client = _StubClient(response={"id": "async"})
    order_req = object()

    result = asyncio.run(submit_order_async(client, order_req))

    assert client.calls == [order_req]
    assert result == {"id": "async"}
