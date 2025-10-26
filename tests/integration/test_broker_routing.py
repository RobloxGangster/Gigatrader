from __future__ import annotations

from backend.brokers import AlpacaBrokerAdapter, MockBrokerAdapter
from backend.services.broker_factory import make_broker_adapter


def _configure_alpaca_env(monkeypatch) -> None:
    monkeypatch.setenv("BROKER", "alpaca")
    monkeypatch.setenv("PROFILE", "paper")
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("ALPACA_KEY_ID", "test_key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test_secret")
    monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")


def test_make_broker_adapter_returns_alpaca(monkeypatch):
    _configure_alpaca_env(monkeypatch)
    adapter = make_broker_adapter()
    assert isinstance(adapter, AlpacaBrokerAdapter)
    assert adapter.profile == "paper"
    assert adapter.dry_run is False


def test_make_broker_adapter_returns_mock(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "true")
    adapter = make_broker_adapter()
    assert isinstance(adapter, MockBrokerAdapter)
