from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

import pandas as pd

from app.data.market import IMarketDataClient, bars_to_df
from .features import build_features
from .models import DEFAULT_MODEL_NAME
from .selection import evaluate_candidates

logger = logging.getLogger(__name__)


def make_labels(df: pd.DataFrame, horizon: int = 15, threshold: float = 0.001) -> pd.Series:
    future = df["close"].shift(-horizon)
    ret = (future - df["close"]) / (df["close"] + 1e-9)
    labels = (ret >= threshold).astype(int)
    labels = labels.iloc[:-horizon]
    return labels.reset_index(drop=True)


def train_intraday_classifier(
    symbols: Iterable[str],
    client: IMarketDataClient,
    out_dir: str | Path = "artifacts/registry",
) -> dict[str, dict[str, float]]:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    metrics: dict[str, dict[str, float]] = {}

    for symbol in symbols:
        bars = client.get_bars(symbol, timeframe="1Min", limit=2000)
        df = bars_to_df(bars)
        feature_df, _ = build_features(df)
        labels = make_labels(df.iloc[-len(feature_df) :].reset_index(drop=True))
        # align lengths
        min_len = min(len(feature_df), len(labels))
        feature_df = feature_df.iloc[:min_len]
        labels = labels.iloc[:min_len]
        result = evaluate_candidates(feature_df, labels)
        metrics[symbol] = result.metrics
        artifact_path = out_path / f"{DEFAULT_MODEL_NAME}.joblib"
        result.sklearn_model.save(artifact_path)
        logger.info("Trained model for %s with metrics %s", symbol, result.metrics)
    return metrics


def latest_feature_row(symbol: str, client: IMarketDataClient) -> tuple[pd.DataFrame, dict]:
    bars = client.get_bars(symbol, timeframe="1Min", limit=500)
    df = bars_to_df(bars)
    feature_df, meta = build_features(df)
    if feature_df.empty:
        raise RuntimeError("Insufficient data for features")
    last = feature_df.tail(1)
    return last, meta
