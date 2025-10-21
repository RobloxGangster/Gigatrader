from __future__ import annotations

from app.execution.adapters import MockBrokerAdapter, make_broker_adapter
from app.execution.alpaca_adapter import AlpacaAdapter
from core.runtime_flags import RuntimeFlags


def test_make_broker_adapter_returns_alpaca(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("PAPER", "true")
    runtime = RuntimeFlags.from_env()
    adapter = make_broker_adapter(runtime)
    assert isinstance(adapter, AlpacaAdapter)


def test_make_broker_adapter_returns_mock(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "true")
    runtime = RuntimeFlags.from_env()
    adapter = make_broker_adapter(runtime)
    assert isinstance(adapter, MockBrokerAdapter)
