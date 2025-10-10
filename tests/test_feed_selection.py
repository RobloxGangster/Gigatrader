from app.data.quality import resolve_data_feed_name


def test_defaults_to_iex(monkeypatch):
    monkeypatch.delenv("ALPACA_DATA_FEED", raising=False)
    assert resolve_data_feed_name() == "iex"


def test_sip_when_env_set(monkeypatch):
    monkeypatch.setenv("ALPACA_DATA_FEED", "SIP")
    assert resolve_data_feed_name() == "sip"


def test_unknown_value_falls_back_to_iex(monkeypatch):
    monkeypatch.setenv("ALPACA_DATA_FEED", "custom")
    assert resolve_data_feed_name() == "iex"
