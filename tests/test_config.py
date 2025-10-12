"""Tests for configuration loading."""

import pytest

from app.config import get_settings


def test_missing_keys_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALPACA_API_KEY_ID", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError):
        get_settings()


def test_defaults_and_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_API_KEY_ID", "abc")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "def")
    monkeypatch.setenv("ALPACA_PAPER", "true")
    monkeypatch.setenv("ALPACA_DATA_FEED", "iex")
    monkeypatch.setenv("SMOKE_SYMBOLS", "AAPL, msft , SPY")
    settings = get_settings()
    assert settings.paper is True
    assert settings.data_feed == "iex"
    assert settings.smoke_symbols == ["AAPL", "MSFT", "SPY"]


def test_old_env_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALPACA_API_KEY_ID", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET_KEY", raising=False)
    monkeypatch.setenv("ALPACA_API_KEY", "oldkey")
    monkeypatch.setenv("ALPACA_API_SECRET", "oldsecret")

    settings = get_settings()
    assert settings.alpaca_key_id == "oldkey"
    assert settings.alpaca_secret_key == "oldsecret"
