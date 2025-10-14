import json
import types

import pytest
from alpaca.common.exceptions import APIError

from app.execution.alpaca_adapter import AlpacaAdapter, AlpacaUnauthorized


@pytest.fixture(autouse=True)
def alpaca_env(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY_ID", "TESTKEY1234")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "SECRET")
    monkeypatch.delenv("APCA_API_BASE_URL", raising=False)
    yield
    monkeypatch.delenv("ALPACA_API_KEY_ID", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET_KEY", raising=False)


class _FakeClient:
    def __init__(self):
        self._submit_behavior = []
        self._submit_calls = 0
        self._cancel_calls: list[str] = []
        self._orders = []
        self._cancel_side_effect: dict[str, Exception] = {}

    def submit_order(self, order_data):
        behavior = None
        if self._submit_calls < len(self._submit_behavior):
            behavior = self._submit_behavior[self._submit_calls]
        self._submit_calls += 1
        if isinstance(behavior, Exception):
            raise behavior
        if callable(behavior):
            return behavior(order_data)
        return behavior

    def get_orders(self):
        return list(self._orders)

    def cancel_order_by_id(self, order_id: str):
        self._cancel_calls.append(order_id)
        exc = self._cancel_side_effect.get(order_id)
        if exc is not None:
            raise exc

    def close_all_positions(self, cancel_orders: bool = True):  # pragma: no cover - not exercised here
        return []

    def get_account(self):  # pragma: no cover - not used here
        return {}


def _api_error(message: str, code: int | None = None) -> APIError:
    payload = {"message": message, "code": code if code is not None else 0}
    return APIError(json.dumps(payload))


def test_place_limit_bracket_unauthorized_raises(monkeypatch):
    client = _FakeClient()
    client._submit_behavior = [_api_error("unauthorized.")]
    monkeypatch.setattr(
        "app.execution.alpaca_adapter.TradingClient",
        lambda *args, **kwargs: client,
    )

    adapter = AlpacaAdapter()
    with pytest.raises(AlpacaUnauthorized):
        adapter.place_limit_bracket("AAPL", "buy", 1, 10.0)

    info = adapter.debug_info()
    assert info["last_error"] == "unauthorized"
    assert info["key_tail"] == "1234"


def test_place_limit_bracket_duplicate_client_id_retry(monkeypatch):
    calls: list[str] = []

    class FakeClient(_FakeClient):
        def submit_order(self, order_data):
            calls.append(order_data.client_order_id)
            if len(calls) == 1:
                raise _api_error("duplicate", code=40010001)
            return types.SimpleNamespace(
                id="order-1",
                client_order_id=order_data.client_order_id,
                symbol="AAPL",
                side="buy",
                qty="1",
                limit_price="10",
                status="accepted",
                submitted_at="2023-01-01T00:00:00Z",
            )

    monkeypatch.setattr(
        "app.execution.alpaca_adapter.TradingClient",
        lambda *args, **kwargs: FakeClient(),
    )

    adapter = AlpacaAdapter()
    result = adapter.place_limit_bracket("AAPL", "buy", 1, 10.0)

    assert len(calls) == 2
    assert result["id"] == "order-1"
    assert result["client_order_id"] == calls[-1]
    assert result["limit_price"] == 10.0
    assert result["qty"] == 1.0


def test_cancel_all_iterates_orders(monkeypatch):
    client = _FakeClient()
    client._orders = [
        types.SimpleNamespace(id="1", status="accepted"),
        types.SimpleNamespace(id="2", status="new"),
        types.SimpleNamespace(id="3", status="filled"),
    ]
    client._cancel_side_effect = {"2": _api_error("fail")}

    monkeypatch.setattr(
        "app.execution.alpaca_adapter.TradingClient",
        lambda *args, **kwargs: client,
    )

    adapter = AlpacaAdapter()
    result = adapter.cancel_all()

    assert result == {"canceled": 1, "failed": 1}
    assert client._cancel_calls == ["1", "2"]


def test_debug_info_tracks_last_error(monkeypatch):
    client = _FakeClient()
    client._submit_behavior = [_api_error("unauthorized.")]

    monkeypatch.setattr(
        "app.execution.alpaca_adapter.TradingClient",
        lambda *args, **kwargs: client,
    )

    adapter = AlpacaAdapter()
    with pytest.raises(AlpacaUnauthorized):
        adapter.place_limit_bracket("AAPL", "buy", 1, 10.0)

    info = adapter.debug_info()
    assert info["last_error"] == "unauthorized"
    assert info["key_tail"] == "1234"
    assert info["paper"] is True
    assert "base_url" in info
