from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api import app


client = TestClient(app)


def test_indicators_missing_symbol_returns_empty_payload() -> None:
    response = client.get("/indicators", params={"symbol": "zzzz", "lookback": 50})
    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "ZZZZ"
    assert payload["has_data"] is False
    assert payload["indicators"] == {}


def test_indicators_accepts_lowercase_symbol() -> None:
    response = client.get("/indicators", params={"symbol": "aapl", "lookback": 500})
    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "AAPL"
    assert payload["interval"] == "1m"
    assert payload["has_data"] is True
    assert "rsi" in payload["indicators"]
    rsi_series = payload["indicators"]["rsi"]
    assert isinstance(rsi_series, list)
    assert any(point.get("value") is not None for point in rsi_series if isinstance(point, dict))


def test_indicators_with_insufficient_lookback_returns_empty() -> None:
    response = client.get("/indicators", params={"symbol": "AAPL", "lookback": 5})
    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "AAPL"
    assert payload["has_data"] is False
    assert payload["indicators"] == {}
