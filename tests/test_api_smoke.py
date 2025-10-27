import os
import importlib
import pytest

# If fastapi isn't installed in the executing environment (e.g., Codex CI), skip gracefully
try:
    from fastapi.testclient import TestClient  # brings starlette+httpx
except Exception:
    pytest.skip("fastapi not installed in this environment; skipping API smoke", allow_module_level=True)

os.environ.setdefault("SERVICE_PORT", "8000")
os.environ.setdefault("MOCK_MODE", "true")
os.environ.setdefault("BROKER", "mock")

app_module = importlib.import_module("backend.server")
app = getattr(app_module, "app")
client = TestClient(app)

def test_health_status():
    health_resp = client.get("/health")
    assert health_resp.status_code == 200
    health = health_resp.json()
    assert isinstance(health.get("ok"), bool)
    assert "broker" in health
    assert "stream_source" in health
    assert "orchestrator_state" in health
    r = client.get("/status")
    assert r.status_code == 200
    body = r.json()
    assert "mode" in body and "profile" in body

def test_orders_positions_without_keys():
    assert client.get("/orders").status_code in (200, 400, 502)
    assert client.get("/positions").status_code in (200, 400, 502)

def test_sentiment_ok_even_without_keys():
    r = client.get("/sentiment", params={"symbol": "AAPL", "hours_back": 1, "limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert "symbol" in body


def test_pacing_endpoint_available():
    response = client.get("/pacing")
    assert response.status_code == 200
    data = response.json()
    assert {"rpm", "history", "max_rpm"}.issubset(data.keys())
