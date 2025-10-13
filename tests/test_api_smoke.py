import os
import importlib
from fastapi.testclient import TestClient

# Ensure dotenv is loaded the same way the app does
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
    # Without Alpaca keys set, our API should respond 400 (not 500)
    assert client.get("/orders").status_code in (200, 400)
    assert client.get("/positions").status_code in (200, 400)

def test_sentiment_ok_even_without_keys():
    r = client.get("/sentiment", params={"symbol": "AAPL", "hours_back": 1, "limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert "symbol" in body
    # score may be None or float depending on env, but should not error
