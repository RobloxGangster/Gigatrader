from __future__ import annotations

from typing import Callable, Iterable

import pytest
from fastapi.testclient import TestClient

from backend import api as backend_api


@pytest.fixture(scope="module")
def api_client() -> TestClient:
    return TestClient(backend_api.app)


def test_orchestrator_status_contract(api_client: TestClient) -> None:
    response = api_client.get("/orchestrator/status")
    assert response.status_code == 200
    payload = response.json()

    required_keys: Iterable[str] = (
        "state",
        "transition",
        "kill_switch",
        "will_trade_at_open",
        "preopen_queue_count",
        "broker",
    )
    for key in required_keys:
        assert key in payload, f"Expected '{key}' in orchestrator status payload"

    assert payload["state"] in {"running", "stopped"}
    # Transition may be None when idle but must exist.
    assert payload.get("transition") in {None, "starting", "stopping", "running", "stopped"}
    assert isinstance(payload["kill_switch"], dict)
    assert "engaged" in payload["kill_switch"]
    assert isinstance(payload["broker"], dict)
    assert {"broker", "profile", "mode"}.issubset(payload["broker"].keys())
    assert isinstance(payload["preopen_queue_count"], int)
    assert isinstance(payload["will_trade_at_open"], bool)


def _validate_metrics_summary(body: dict) -> bool:
    return (
        isinstance(body, dict)
        and body.get("counts", {}) == {}
        and body.get("exposure", {}) == {}
        and body.get("pnl") in (0, 0.0, None)
    )


def _validate_feature_indicators(body: object) -> bool:
    return (
        isinstance(body, dict)
        and isinstance(body.get("indicators"), (list, dict))
        and isinstance(body.get("has_data"), bool)
        and "symbol" in body
    )


def _is_dict_response(body: object) -> bool:
    return isinstance(body, dict)


def _is_list_response(body: object) -> bool:
    return isinstance(body, list)


@pytest.mark.parametrize(
    "path, validator",
    (
        ("/trades", _is_list_response),
        ("/metrics/summary", _validate_metrics_summary),
        ("/features/indicators/AAPL", _validate_feature_indicators),
        ("/broker/orders", _is_list_response),
        ("/broker/positions", _is_list_response),
        ("/broker/account", _is_dict_response),
    ),
)
def test_empty_endpoints_are_200(
    api_client: TestClient, path: str, validator: Callable[[object], bool]
) -> None:
    response = api_client.get(path)
    assert response.status_code == 200, f"{path} should return HTTP 200"
    payload = response.json()
    assert validator(payload), f"Unexpected payload for {path}: {payload!r}"
