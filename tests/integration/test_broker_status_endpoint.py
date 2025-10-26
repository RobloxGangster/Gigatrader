from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def test_broker_status_reflects_alpaca_when_not_mock(monkeypatch):
    monkeypatch.setenv("BROKER", "alpaca")
    monkeypatch.setenv("PROFILE", "paper")
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("ALPACA_KEY_ID", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    backend_api = importlib.import_module("backend.api")
    backend_api = importlib.reload(backend_api)

    client = TestClient(backend_api.app)
    resp = client.get("/broker/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["impl"] == "AlpacaBrokerAdapter"
    assert body["profile"] == "paper"
    assert body["dry_run"] is False


def test_broker_status_reflects_mock_when_enabled(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "true")

    backend_api = importlib.import_module("backend.api")
    backend_api = importlib.reload(backend_api)

    client = TestClient(backend_api.app)
    resp = client.get("/broker/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["impl"] == "MockBrokerAdapter"
