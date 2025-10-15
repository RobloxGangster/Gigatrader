from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any, Iterable, List, Tuple

import numpy as np
import pandas as pd


@dataclass
class GateReport:
    """Small helper structure describing the outcome of a guardrail."""

    name: str
    value: float
    threshold: float
    passed: bool
    details: Dict[str, Any] = field(default_factory=dict)


def _average_precision_score(y_true: np.ndarray, y_score: np.ndarray) -> float:
    positives = float(y_true.sum())
    if positives <= 0 or positives >= len(y_true):
        return float("nan")
    order = np.argsort(-y_score)
    y_true_sorted = y_true[order]
    precision = np.cumsum(y_true_sorted) / (np.arange(len(y_true_sorted)) + 1)
    ap = (precision * y_true_sorted).sum() / positives
    return float(ap)


def population_stability_index(expected: Iterable[float], actual: Iterable[float], *, epsilon: float = 1e-9) -> float:
    """Compute the Population Stability Index (PSI).

    Parameters
    ----------
    expected: Iterable[float]
        Baseline probabilities per bucket.
    actual: Iterable[float]
        Observed probabilities per bucket.
    epsilon: float
        Small constant to avoid division by zero.
    """

    exp = np.asarray(expected, dtype=float)
    act = np.asarray(actual, dtype=float)
    if exp.shape != act.shape:
        raise ValueError("Expected and actual must have the same shape for PSI computation.")

    exp = exp + epsilon
    act = act + epsilon

    exp = exp / exp.sum()
    act = act / act.sum()

    ratio = act / exp
    psi = np.sum((act - exp) * np.log(ratio))
    return float(psi)


def compute_feature_snapshot(df: pd.DataFrame, *, bins: int = 10, epsilon: float = 1e-9) -> Dict[str, Any]:
    """Create a histogram snapshot for each feature to serve as PSI baseline."""

    snapshot: Dict[str, Any] = {"bins": bins, "features": {}}
    for column in df.columns:
        series = df[column].dropna()
        if series.empty:
            continue
        counts, edges = np.histogram(series, bins=bins)
        probs = (counts + epsilon)
        probs = probs / probs.sum()
        snapshot["features"][column] = {"bins": edges.tolist(), "probs": probs.tolist()}
    return snapshot


def psi_against_snapshot(df: pd.DataFrame, snapshot: Dict[str, Any], *, epsilon: float = 1e-9) -> Dict[str, float]:
    """Compute PSI for each feature in *df* against the stored snapshot."""

    if not snapshot:
        return {}

    feature_stats = snapshot.get("features", snapshot)
    results: Dict[str, float] = {}
    for column, stats in feature_stats.items():
        if column not in df.columns:
            continue
        series = df[column].dropna()
        if series.empty:
            continue
        bins = np.asarray(stats.get("bins"))
        counts, _ = np.histogram(series, bins=bins)
        actual = (counts + epsilon)
        actual = actual / actual.sum()
        expected = np.asarray(stats.get("probs", []), dtype=float)
        if expected.size != actual.size:
            continue
        results[column] = population_stability_index(expected, actual, epsilon=epsilon)
    return results


def evaluate_data_drift(df: pd.DataFrame, snapshot: Dict[str, Any], *, psi_threshold: float = 0.2) -> Tuple[Dict[str, float], List[GateReport]]:
    """Compute PSI values and associated PASS/FAIL reports."""

    psi_values = psi_against_snapshot(df, snapshot)
    reports = [
        GateReport(
            name=f"data.psi.{feature}",
            value=value,
            threshold=psi_threshold,
            passed=value <= psi_threshold,
            details={"feature": feature},
        )
        for feature, value in psi_values.items()
    ]
    return psi_values, reports


def _daily_metrics(df: pd.DataFrame, *, target_col: str, proba_col: str) -> pd.DataFrame:
    rows = []
    for date, group in df.groupby("date", sort=True):
        y_true = group[target_col].astype(float).to_numpy()
        y_score = group[proba_col].astype(float).to_numpy()
        brier = float(np.mean((y_score - y_true) ** 2))
        pr_auc = _average_precision_score(y_true, y_score)
        rows.append({"date": pd.to_datetime(date), "brier": brier, "pr_auc": pr_auc})
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def rolling_performance_metrics(
    df: pd.DataFrame,
    *,
    window_days: int,
    timestamp_col: str = "timestamp",
    target_col: str = "y_true",
    proba_col: str = "y_pred",
) -> pd.DataFrame:
    """Compute daily metrics and rolling aggregates for realised outcomes."""

    if df.empty:
        raise ValueError("Performance frame is empty; cannot compute drift metrics.")

    perf = df.copy()
    perf[timestamp_col] = pd.to_datetime(perf[timestamp_col])
    perf["date"] = perf[timestamp_col].dt.normalize()
    daily = _daily_metrics(perf, target_col=target_col, proba_col=proba_col)
    daily["pr_auc_roll"] = daily["pr_auc"].rolling(window_days, min_periods=1).mean()
    daily["brier_roll"] = daily["brier"].rolling(window_days, min_periods=1).mean()
    return daily


def evaluate_performance_drift(
    df: pd.DataFrame,
    *,
    window_days: int,
    pr_auc_threshold: float,
    brier_threshold: float,
    timestamp_col: str = "timestamp",
    target_col: str = "y_true",
    proba_col: str = "y_pred",
) -> Tuple[pd.DataFrame, List[GateReport]]:
    """Evaluate rolling performance metrics and the corresponding guardrails."""

    metrics = rolling_performance_metrics(
        df,
        window_days=window_days,
        timestamp_col=timestamp_col,
        target_col=target_col,
        proba_col=proba_col,
    )
    if metrics.empty:
        return metrics, []

    latest = metrics.iloc[-1]
    reports = [
        GateReport(
            name="performance.pr_auc",
            value=float(latest["pr_auc_roll"]),
            threshold=pr_auc_threshold,
            passed=float(latest["pr_auc_roll"]) >= pr_auc_threshold,
        ),
        GateReport(
            name="performance.brier",
            value=float(latest["brier_roll"]),
            threshold=brier_threshold,
            passed=float(latest["brier_roll"]) <= brier_threshold,
        ),
    ]
    return metrics, reports


__all__ = [
    "GateReport",
    "population_stability_index",
    "compute_feature_snapshot",
    "psi_against_snapshot",
    "evaluate_data_drift",
    "rolling_performance_metrics",
    "evaluate_performance_drift",
]
