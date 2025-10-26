from __future__ import annotations

from app.streams import AlpacaStream, MockStream, make_stream
from core.runtime_flags import runtime_flags_from_env


def test_make_stream_returns_alpaca(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("BROKER", "alpaca")
    monkeypatch.setenv("PROFILE", "paper")
    monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    flags = runtime_flags_from_env()
    stream = make_stream(flags)
    assert isinstance(stream, AlpacaStream)
    assert stream.base_url == "https://paper-api.alpaca.markets"


def test_make_stream_returns_mock(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "true")
    monkeypatch.setenv("BROKER", "mock")
    flags = runtime_flags_from_env()
    stream = make_stream(flags)
    assert isinstance(stream, MockStream)
