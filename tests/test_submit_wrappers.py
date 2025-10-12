import asyncio
from types import SimpleNamespace

from app.execution.alpaca_orders import submit_order_async, submit_order_sync


class DummyClient:
    def __init__(self) -> None:
        self.calls = 0

    def submit_order(self, order_data):
        self.calls += 1
        return SimpleNamespace(
            id="abc123", status="accepted", symbol=getattr(order_data, "symbol", None)
        )


def test_sync_wrapper():
    client = DummyClient()
    response = submit_order_sync(client, SimpleNamespace(symbol="MSFT"))
    assert client.calls == 1
    assert response.id == "abc123"


def test_async_wrapper():
    client = DummyClient()

    async def _run():
        response = await submit_order_async(client, SimpleNamespace(symbol="MSFT"))
        assert client.calls == 1
        assert response.symbol == "MSFT"

    asyncio.run(_run())
