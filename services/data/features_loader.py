"""Utilities for loading feature panels from the feature store."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import os

import pandas as pd


def _to_utc_timestamp(value: str) -> pd.Timestamp:
    """Convert a string timestamp into a timezone-aware UTC timestamp."""

    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts


def _ensure_multiindex_utc(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure the DataFrame has a UTC datetime level in its MultiIndex."""

    if not isinstance(df.index, pd.MultiIndex) or df.index.nlevels < 2:
        raise ValueError("Feature store parquet must be indexed by a MultiIndex (datetime, symbol).")

    datetime_values = pd.to_datetime(df.index.get_level_values(0), utc=True)
    symbols = df.index.get_level_values(1)

    names = list(df.index.names)
    if len(names) < 2:
        names = ["timestamp", "symbol"]

    new_index = pd.MultiIndex.from_arrays([datetime_values, symbols], names=names[:2])
    df = df.copy()
    df.index = new_index
    return df


def _iter_feature_store_files(base_path: Path) -> Iterable[Path]:
    return sorted(p for p in base_path.glob("*.parquet") if p.is_file())


def load_feature_panel(symbols: list[str], start: str, end: str) -> pd.DataFrame:
    """
    Return a MultiIndex DataFrame indexed by (datetime, symbol) with columns:
      [<feature columns>..., 'target']  # target is 0/1
    - Must be timezone-aware UTC datetimes.
    - Must guarantee stable column order for training and inference (store order).
    - Read from FEATURE_STORE_PATH (env) as parquet or fallback to runtime/mock parquet.
    """

    start_ts = _to_utc_timestamp(start)
    end_ts = _to_utc_timestamp(end)

    if end_ts < start_ts:
        raise ValueError("end must be greater than or equal to start")

    feature_store_path = Path(os.getenv("FEATURE_STORE_PATH", "artifacts/features"))
    if not feature_store_path.exists():
        raise FileNotFoundError(f"Feature store path does not exist: {feature_store_path}")

    symbol_set = set(symbols)

    collected: list[pd.DataFrame] = []
    column_order: list[str] | None = None

    for file_path in _iter_feature_store_files(feature_store_path):
        df = pd.read_parquet(file_path)
        df = _ensure_multiindex_utc(df)

        datetime_values = df.index.get_level_values(0)
        symbol_values = df.index.get_level_values(1)

        mask = (datetime_values >= start_ts) & (datetime_values <= end_ts)
        if symbol_set:
            mask &= symbol_values.isin(symbol_set)

        if not mask.any():
            continue

        filtered = df.loc[mask]

        if column_order is None:
            column_order = list(filtered.columns)
        else:
            for column in filtered.columns:
                if column not in column_order:
                    column_order.append(column)

        collected.append(filtered)

    if collected:
        result = pd.concat(collected, axis=0)
    else:
        column_order = column_order or []
        empty_index = pd.MultiIndex.from_arrays(
            [pd.DatetimeIndex([], tz="UTC"), pd.Index([], dtype=object)],
            names=["timestamp", "symbol"],
        )
        result = pd.DataFrame(columns=column_order, index=empty_index)

    result = result.sort_index()

    assert isinstance(result.index, pd.MultiIndex), "Feature panel must be indexed by a MultiIndex."
    assert "target" in result.columns, "Feature panel must contain a 'target' column."

    if column_order is not None:
        result = result.loc[:, column_order]

    return result

