import importlib
import sys

from fastapi.testclient import TestClient


def test_mock_endpoints(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "true")
    if "backend.server" in sys.modules:
        importlib.reload(sys.modules["backend.server"])
    server = importlib.import_module("backend.server")
    client = TestClient(server.app)

    resp = client.get("/signals/preview")
    assert resp.status_code == 200
    data = resp.json()
    assert "candidates" in data or "error" in data

    resp = client.post("/backtest/run", json={"symbol": "AAPL", "strategy": "intraday_momo", "days": 10})
    assert resp.status_code == 200
    backtest = resp.json()
    assert "stats" in backtest

    resp = client.get("/ml/status")
    assert resp.status_code == 200
