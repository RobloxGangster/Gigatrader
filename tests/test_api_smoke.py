import os
import importlib
import pytest

# If fastapi isn't installed in the executing environment (e.g., Codex CI), skip gracefully
try:
    from fastapi.testclient import TestClient  # brings starlette+httpx
except Exception:
    pytest.skip("fastapi not installed in this environment; skipping API smoke", allow_module_level=True)

os.environ.setdefault("SERVICE_PORT", "8000")

app_module = importlib.import_module("backend.app")
app = getattr(app_module, "app")
client = TestClient(app)

def test_health_status():
    assert client.get("/health").status_code == 200
    r = client.get("/status")
    assert r.status_code == 200
    body = r.json()
    assert "mode" in body and "profile" in body

def test_orders_positions_without_keys():
    assert client.get("/orders").status_code in (200, 400)
    assert client.get("/positions").status_code in (200, 400)

def test_sentiment_ok_even_without_keys():
    r = client.get("/sentiment", params={"symbol": "AAPL", "hours_back": 1, "limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert "symbol" in body
