from __future__ import annotations

from core.runtime_flags import (
    RuntimeFlags,
    get_runtime_flags,
    parse_bool,
    refresh_runtime_flags,
    runtime_flags_from_env,
)


def test_parse_bool_truthy_cases():
    truthy = ["1", "true", "TRUE", "Yes", "on", "Y", "t"]
    for value in truthy:
        assert parse_bool(value) is True


def test_parse_bool_falsey_cases():
    falsey = ["", "0", "false", "False", "no", "off", "n"]
    for value in falsey:
        assert parse_bool(value, default=True) is False


def test_parse_bool_none_uses_default():
    assert parse_bool(None, default=True) is True
    assert parse_bool(None, default=False) is False


def test_runtime_flags_from_env(monkeypatch):
    monkeypatch.setenv("BROKER", "alpaca")
    monkeypatch.setenv("PROFILE", "paper")
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("API_BASE", "http://localhost:9999")
    monkeypatch.setenv("UI_PORT", "8601")
    flags = runtime_flags_from_env()
    assert flags.mock_mode is False
    assert flags.dry_run is False
    assert flags.broker == "alpaca"
    assert flags.profile == "paper"
    assert flags.paper_trading is True
    assert flags.market_data_source == "alpaca"
    assert flags.alpaca_base_url == "https://paper-api.alpaca.markets"
    assert flags.api_base_url == "http://localhost:9999"
    assert flags.api_port == 8000
    assert flags.ui_port == 8601
    assert flags.auto_restart is True


def test_runtime_flags_refresh_reads_environment(monkeypatch):
    monkeypatch.setenv("BROKER", "alpaca")
    monkeypatch.setenv("MOCK_MODE", "true")
    first = refresh_runtime_flags()
    assert first.mock_mode is True
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("BROKER", "alpaca")
    second = get_runtime_flags()
    assert second.mock_mode is False
    third = refresh_runtime_flags()
    assert third.mock_mode is False


def test_market_data_source_defaults_to_alpaca(monkeypatch):
    monkeypatch.setenv("BROKER", "alpaca")
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.delenv("MARKET_DATA_SOURCE", raising=False)
    flags = runtime_flags_from_env()
    assert flags.market_data_source == "alpaca"


def test_market_data_source_forced_mock_when_mock_mode(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "true")
    monkeypatch.delenv("MARKET_DATA_SOURCE", raising=False)
    flags = runtime_flags_from_env()
    assert flags.market_data_source == "mock"


def test_market_data_source_env_override(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("BROKER", "alpaca")
    monkeypatch.setenv("MARKET_DATA_SOURCE", "mock")
    flags = runtime_flags_from_env()
    assert flags.market_data_source == "mock"
