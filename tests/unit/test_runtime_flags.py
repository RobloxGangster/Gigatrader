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
    falsey = [None, "0", "false", "False", "no", "off", "n"]
    for value in falsey:
        expected = True if value is None else False
        assert parse_bool(value, default=True) is expected


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
    assert flags.alpaca_base_url == "https://paper-api.alpaca.markets"
    assert flags.api_base_url == "http://localhost:9999"
    assert flags.api_port == 8000
    assert flags.ui_port == 8601
    assert flags.auto_restart is True


def test_runtime_flags_refresh_reads_environment(monkeypatch):
    monkeypatch.setenv("BROKER", "alpaca")
    monkeypatch.setenv("MOCK_MODE", "true")
    first = get_runtime_flags()
    assert first.mock_mode is True
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("BROKER", "alpaca")
    second = get_runtime_flags()
    assert second.mock_mode is False
    third = refresh_runtime_flags()
    assert third.mock_mode is False
