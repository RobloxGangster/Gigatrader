import numpy as np

from app.data.market import MockDataClient, bars_to_df
from app.backtest.engine import run_trade_backtest


def test_backtest_result_structure():
    client = MockDataClient()
    bars = client.get_bars("NVDA", timeframe="1Min", limit=200)
    df = bars_to_df(bars).tail(120)
    entry = float(df["close"].iloc[0])
    stop = entry * 0.99
    target = entry * 1.01
    result = run_trade_backtest(df, entry=entry, stop=stop, target=target, side="buy", time_exit=90)
    assert result.stats
    for value in result.stats.values():
        assert np.isfinite(float(value))
    assert result.trades
    assert result.equity_curve
