import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend import api as backend_api
from backend.routers import orchestrator as orchestrator_router


class _StubFlags(SimpleNamespace):
    mock_mode: bool = True
    dry_run: bool = True
    paper_trading: bool = True
    profile: str = "paper"


class _StubOrchestrator:
    def __init__(self) -> None:
        self._status = {"state": "stopped", "running": False}

    def safe_arm_trading(self, *, requested_by: str) -> dict:
        return {"engaged": False}

    def status(self) -> dict:
        return dict(self._status)

    def reset_kill_switch(self, *, requested_by: str) -> None:  # noqa: D401 - stub
        return None


@pytest.fixture(name="api_client")
def _client_fixture(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(orchestrator_router, "get_runtime_flags", lambda: _StubFlags())
    monkeypatch.setattr(orchestrator_router, "require_alpaca_keys", lambda: None)
    stub = _StubOrchestrator()
    monkeypatch.setattr(orchestrator_router, "get_orchestrator", lambda: stub)

    def _loop(stop_requested):
        stub._status = {"state": "running", "running": True}
        start = time.time()
        while not stop_requested():
            if time.time() - start > 0.1:
                break
            time.sleep(0.01)
        stub._status = {"state": "stopped", "running": False}

    monkeypatch.setattr(orchestrator_router, "run_trading_loop", _loop)
    return TestClient(backend_api.app)


def test_orchestrator_idempotent(api_client: TestClient) -> None:
    first_stop = api_client.post("/orchestrator/stop")
    assert first_stop.status_code == 200
    second_stop = api_client.post("/orchestrator/stop")
    assert second_stop.status_code == 200

    first_start = api_client.post("/orchestrator/start")
    assert first_start.status_code == 200
    second_start = api_client.post("/orchestrator/start")
    assert second_start.status_code == 200

    time.sleep(0.05)
    status = api_client.get("/orchestrator/status").json()
    assert status["state"] in {"starting", "running"}

    api_client.post("/orchestrator/stop")


def test_broker_order_alias(api_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    class _StubBroker:
        async def place_order(self, **kwargs):  # noqa: D401 - stub
            return {
                "symbol": kwargs.get("symbol", "AAPL"),
                "qty": kwargs.get("qty", 1),
                "side": kwargs.get("side", "buy"),
                "status": "accepted",
            }

    monkeypatch.setattr(backend_api, "get_trade_broker", lambda: _StubBroker())

    payload = {
        "symbol": "AAPL",
        "qty": 1,
        "side": "buy",
        "type": "market",
        "time_in_force": "day",
    }
    for path in ("/broker/order", "/broker/orders"):
        response = api_client.post(path, json=payload)
        assert response.status_code == 200
        body = response.json()
        assert body.get("symbol") == "AAPL"


def test_metrics_trades_empty_ok(api_client: TestClient) -> None:
    metrics_resp = api_client.get("/metrics/summary")
    trades_resp = api_client.get("/trades")
    assert metrics_resp.status_code == 200
    assert trades_resp.status_code == 200
