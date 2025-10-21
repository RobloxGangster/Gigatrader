from __future__ import annotations

from app.streams import AlpacaStream, MockStream, make_stream
from core.runtime_flags import RuntimeFlags


def test_make_stream_returns_alpaca(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("PAPER", "true")
    flags = RuntimeFlags.from_env()
    stream = make_stream(flags)
    assert isinstance(stream, AlpacaStream)
    assert stream.base_url == "https://paper-api.alpaca.markets"


def test_make_stream_returns_mock(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "true")
    flags = RuntimeFlags.from_env()
    stream = make_stream(flags)
    assert isinstance(stream, MockStream)
