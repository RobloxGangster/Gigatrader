import os

import pytest
import requests

API = f"http://127.0.0.1:{os.getenv('GT_API_PORT', '8000')}"


@pytest.mark.usefixtures("server_stack")
def test_telemetry_metrics_shape():
    response = requests.get(f"{API}/telemetry/metrics", timeout=10)
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, dict)
    for key in ("equity", "buying_power", "day_pl", "positions", "risk", "orchestrator"):
        assert key in payload
    assert isinstance(payload.get("positions"), list)
    orchestrator = payload.get("orchestrator") or {}
    assert isinstance(orchestrator, dict)
    assert "state" in orchestrator
    assert "can_trade" in orchestrator


@pytest.mark.usefixtures("server_stack")
def test_telemetry_trades_list():
    response = requests.get(f"{API}/telemetry/trades", timeout=10)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
