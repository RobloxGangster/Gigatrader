from pathlib import Path

from app.data.market import MockDataClient, bars_to_df


def test_mock_bars_and_quotes():
    client = MockDataClient(base_dir=Path("fixtures"))
    bars = client.get_bars("AAPL", timeframe="1Min", limit=50)
    assert len(bars) == 50
    df = bars_to_df(bars)
    assert df.shape[0] == 50
    assert df["time"].is_monotonic_increasing
    assert df[["open", "high", "low", "close", "volume"]].notna().all().all()

    quote = client.get_quote("AAPL")
    assert "bid" in quote and "ask" in quote


def test_mock_option_chain():
    client = MockDataClient(base_dir=Path("fixtures"))
    chain = client.get_option_chain("AAPL")
    assert chain["options"]
    assert chain["options"][0]["type"] in {"call", "put"}
