import importlib


def test_stream_factory_prefers_alpaca_when_not_mock(monkeypatch):
    monkeypatch.setenv("BROKER", "alpaca")
    monkeypatch.setenv("PROFILE", "paper")
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.delenv("MARKET_DATA_SOURCE", raising=False)

    module = importlib.import_module("backend.services.stream_factory")
    importlib.reload(module)
    svc = module.make_stream_service()
    assert type(svc).__name__ == "AlpacaStreamService"


def test_stream_factory_respects_mock(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "true")
    monkeypatch.delenv("MARKET_DATA_SOURCE", raising=False)
    module = importlib.import_module("backend.services.stream_factory")
    importlib.reload(module)
    svc = module.make_stream_service()
    assert type(svc).__name__ == "MockStreamService"
