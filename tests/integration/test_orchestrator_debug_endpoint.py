from fastapi.testclient import TestClient

from backend import api as backend_api
from backend.routers import orchestrator as orchestrator_router


def test_orchestrator_debug_endpoint(monkeypatch):
    monkeypatch.setenv("BROKER", "alpaca")
    monkeypatch.setenv("PROFILE", "paper")
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("DRY_RUN", "false")

    status_payload = {
        "state": "running",
        "running": True,
        "kill_switch": "Standby",
        "kill_switch_engaged": False,
        "broker_impl": "AlpacaBrokerAdapter",
        "market_data_source": "alpaca",
        "profile": "paper",
        "dry_run": False,
        "uptime": "10.00s",
    }
    attempt_payload = {
        "ts": "2024-01-01T00:00:00Z",
        "symbol": "AAPL",
        "side": "buy",
        "qty": 5,
        "sent": True,
        "accepted": True,
        "reason": "accepted",
        "broker_impl": "AlpacaBrokerAdapter",
    }

    monkeypatch.setattr(
        orchestrator_router,
        "get_orchestrator_status",
        lambda: status_payload,
    )
    monkeypatch.setattr(
        orchestrator_router,
        "get_last_order_attempt",
        lambda: attempt_payload,
    )

    client = TestClient(backend_api.app)
    response = client.get("/orchestrator/debug")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"]["broker_impl"] == "AlpacaBrokerAdapter"
    assert payload["last_order_attempt"]["symbol"] == "AAPL"
    assert payload["status"]["market_data_source"] == "alpaca"
