import numpy as np
import pandas as pd

from app.data.market import MockDataClient, bars_to_df
from app.ml.features import FEATURE_LIST, build_features


def test_build_features_shapes():
    client = MockDataClient()
    bars = client.get_bars("MSFT", timeframe="1Min", limit=600)
    df = bars_to_df(bars)
    feature_df, meta = build_features(df)
    assert list(feature_df.columns) == FEATURE_LIST
    assert feature_df.iloc[-1].apply(np.isfinite).all()
    assert meta["rows"] == len(feature_df)
