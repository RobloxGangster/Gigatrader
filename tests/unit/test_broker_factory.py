from backend.brokers import AlpacaBrokerAdapter
from backend.services.broker_factory import make_broker_adapter
from core.runtime_flags import runtime_flags_from_env


def test_make_broker_adapter_returns_alpaca(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("BROKER", "alpaca")
    monkeypatch.setenv("ALPACA_KEY_ID", "test-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    flags = runtime_flags_from_env()
    adapter = make_broker_adapter(flags)

    assert isinstance(adapter, AlpacaBrokerAdapter)
