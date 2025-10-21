from __future__ import annotations

from core.runtime_flags import RuntimeFlags, get_runtime_flags, parse_bool


def test_parse_bool_truthy_cases():
    truthy = ["1", "true", "TRUE", "Yes", "on", "Y", "t"]
    for value in truthy:
        assert parse_bool(value) is True


def test_parse_bool_falsey_cases():
    falsey = [None, "0", "false", "False", "no", "off", "n"]
    for value in falsey:
        assert parse_bool(value, default=True) is (value is None)


def test_runtime_flags_from_env(monkeypatch):
    monkeypatch.setenv("BROKER_MODE", "paper")
    monkeypatch.setenv("API_BASE", "http://localhost:9999")
    monkeypatch.setenv("UI_PORT", "8601")
    flags = RuntimeFlags.from_env()
    assert flags.mock_mode is False
    assert flags.broker_mode == "paper"
    assert flags.paper_trading is True
    assert flags.alpaca_base_url == "https://paper-api.alpaca.markets"
    assert flags.api_base_url == "http://localhost:9999"
    assert flags.api_port == 8000
    assert flags.ui_port == 8601


def test_runtime_flags_cache(monkeypatch):
    monkeypatch.setenv("BROKER_MODE", "mock")
    get_runtime_flags.cache_clear()  # type: ignore[attr-defined]
    first = get_runtime_flags()
    monkeypatch.setenv("BROKER_MODE", "paper")
    second = get_runtime_flags()
    assert first.mock_mode is True
    assert second.mock_mode is True
