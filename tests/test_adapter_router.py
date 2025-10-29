import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import os

from app.execution.alpaca_adapter import AlpacaAdapter
from app.execution.router import AlpacaRouter, MockRouter, build_router
from backend.routers import broker
from core.settings import Settings


@pytest.fixture(autouse=True)
def alpaca_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_KEY_ID", "test-key")
    monkeypatch.setenv("ALPACA_API_KEY_ID", "test-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    monkeypatch.setenv("PROFILE", "paper")
    monkeypatch.setenv("BROKER", "alpaca")
    monkeypatch.setenv("DRY_RUN", "false")
    yield
    monkeypatch.delenv("ALPACA_KEY_ID", raising=False)
    monkeypatch.delenv("ALPACA_API_KEY_ID", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET_KEY", raising=False)
    monkeypatch.delenv("ALPACA_BASE_URL", raising=False)
    monkeypatch.delenv("PROFILE", raising=False)
    monkeypatch.delenv("BROKER", raising=False)
    monkeypatch.delenv("DRY_RUN", raising=False)


class FakeResponse:
    def __init__(self, json_data, status_code: int = 200) -> None:
        self._json = json_data
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._json

    def raise_for_status(self) -> None:
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, json_payload) -> None:
        self.json_payload = json_payload
        self.last_post = None
        self.headers = {}

    def post(self, url, timeout=None, **kwargs):
        self.last_post = (url, kwargs)
        body = dict(kwargs.get("json", {}))
        body.setdefault("id", "order-1")
        return FakeResponse(body)

    def get(self, url, timeout=None, **kwargs):
        return FakeResponse(self.json_payload)

    def delete(self, url, timeout=None, **kwargs):
        return FakeResponse({}, status_code=204)


def _build_stubbed_broker_client() -> TestClient:
    app = FastAPI()
    app.include_router(broker.router, prefix="/broker")
    client = TestClient(app)

    class StubAdapter:
        def list_orders(self, status: str = "all", limit: int = 50):
            return [
                {
                    "id": "order-1",
                    "client_order_id": "cid-1",
                    "symbol": "AAPL",
                    "qty": "1",
                    "filled_qty": "0",
                    "status": "accepted",
                    "side": "buy",
                    "type": "limit",
                    "limit_price": "10",
                    "submitted_at": "2023-01-01T00:00:00Z",
                }
            ]

    stub_adapter = StubAdapter()

    class StubService:
        def __init__(self) -> None:
            self.adapter = stub_adapter
            self.flags = type(
                "Flags",
                (),
                {"broker": "alpaca", "mock_mode": False, "dry_run": False},
            )()

        def get_orders(self, status: str = "all", limit: int = 50):
            return stub_adapter.list_orders(status=status, limit=limit)

        def last_headers(self):
            return {}

    app.dependency_overrides[broker.get_broker_adapter] = lambda: stub_adapter
    app.dependency_overrides[broker.get_broker] = lambda: StubService()

    return client


def test_place_order_hits_alpaca() -> None:
    payload = {
        "symbol": "AAPL",
        "qty": 1,
        "side": "buy",
        "type": "market",
        "client_order_id": "cid-1",
    }
    session = FakeSession(json_payload=[])
    adapter = AlpacaAdapter(session=session)

    result = adapter.place_order(payload)

    assert result["id"] == "order-1"
    url, kwargs = session.last_post
    assert url == "https://paper-api.alpaca.markets/v2/orders"
    assert kwargs["json"]["client_order_id"] == "cid-1"


def test_broker_orders_route_returns_normalised() -> None:
    client = _build_stubbed_broker_client()

    response = client.get("/broker/orders")
    assert response.status_code == 200
    body = response.json()
    assert body[0]["status"] == "accepted"
    assert body[0]["id"] == "order-1"


def test_broker_trades_alias_returns_orders() -> None:
    client = _build_stubbed_broker_client()

    response = client.get("/broker/trades")
    assert response.status_code == 200
    body = response.json()
    assert body[0]["status"] == "accepted"
    assert body[0]["id"] == "order-1"


def test_build_router_prefers_alpaca(monkeypatch: pytest.MonkeyPatch) -> None:
    assert os.getenv("ALPACA_KEY_ID") == "test-key"
    assert os.getenv("ALPACA_SECRET_KEY") == "test-secret"
    monkeypatch.setenv("ALPACA_KEY_ID", "test-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")
    settings = Settings.from_env()
    router = build_router(settings)
    assert isinstance(router, AlpacaRouter)

    monkeypatch.setenv("BROKER", "mock")
    monkeypatch.setenv("PROFILE", "dev")
    monkeypatch.delenv("ALPACA_KEY_ID", raising=False)
    monkeypatch.delenv("ALPACA_API_KEY_ID", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET_KEY", raising=False)
    mock_settings = Settings.from_env()
    with pytest.raises(RuntimeError):
        build_router(mock_settings)
