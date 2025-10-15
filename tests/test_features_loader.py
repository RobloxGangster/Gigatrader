from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from services.data.features_loader import load_feature_panel


def _write_parquet(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)


def test_load_feature_panel_returns_sorted_multiindex(tmp_path, monkeypatch):
    store_path = tmp_path / "features"
    dates = pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC")
    symbols = ["AAPL", "MSFT"]
    index = pd.MultiIndex.from_product([dates, symbols], names=["timestamp", "symbol"])
    df_main = pd.DataFrame(
        {
            "feat1": range(len(index)),
            "feat2": range(len(index), 2 * len(index)),
            "target": [0, 1] * (len(index) // 2),
        },
        index=index,
    )

    _write_parquet(store_path / "part1.parquet", df_main)

    extra_dates = pd.date_range("2024-02-01", periods=2, freq="D", tz="UTC")
    extra_index = pd.MultiIndex.from_product([extra_dates, symbols], names=["timestamp", "symbol"])
    df_extra = pd.DataFrame(
        {
            "feat1": [10, 11, 12, 13],
            "feat2": [14, 15, 16, 17],
            "target": [1, 0, 1, 0],
        },
        index=extra_index,
    )

    _write_parquet(store_path / "part2.parquet", df_extra)

    monkeypatch.setenv("FEATURE_STORE_PATH", str(store_path))

    result = load_feature_panel(["AAPL", "MSFT"], "2024-01-01", "2024-01-03")

    expected_index = index.sort_values()

    assert list(result.columns) == ["feat1", "feat2", "target"]
    assert result.index.equals(expected_index)
    assert result.index.get_level_values(0).tz is not None
    assert "target" in result.columns
    assert result.shape == (len(expected_index), 3)


def test_load_feature_panel_filters_symbols(tmp_path, monkeypatch):
    store_path = tmp_path / "features"
    dates = pd.date_range("2024-01-01", periods=2, freq="D", tz="UTC")
    symbols = ["AAPL", "MSFT"]
    index = pd.MultiIndex.from_product([dates, symbols], names=["timestamp", "symbol"])
    df = pd.DataFrame(
        {
            "feat1": [1, 2, 3, 4],
            "target": [0, 1, 0, 1],
        },
        index=index,
    )

    _write_parquet(store_path / "part.parquet", df)

    monkeypatch.setenv("FEATURE_STORE_PATH", str(store_path))

    result = load_feature_panel(["AAPL"], "2024-01-01", "2024-01-02")

    expected_index = pd.MultiIndex.from_product(
        [dates, ["AAPL"]], names=["timestamp", "symbol"]
    )

    assert result.index.equals(expected_index)
    assert list(result.columns) == ["feat1", "target"]

