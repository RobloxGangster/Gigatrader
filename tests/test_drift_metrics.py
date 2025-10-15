import numpy as np
import pandas as pd
import pytest

from services.ml.drift import (
    population_stability_index,
    compute_feature_snapshot,
    evaluate_data_drift,
    evaluate_performance_drift,
)


def test_population_stability_index_matches_manual():
    expected = np.array([0.2, 0.5, 0.3])
    actual = np.array([0.25, 0.45, 0.30])
    manual = np.sum((actual - expected) * np.log(actual / expected))
    psi = population_stability_index(expected, actual)
    assert psi == pytest.approx(manual)


def test_psi_thresholds_trigger_pass_and_fail():
    baseline = pd.DataFrame({"f1": [0] * 50 + [1] * 50})
    snapshot = compute_feature_snapshot(baseline, bins=2)
    current = pd.DataFrame({"f1": [0] * 70 + [1] * 30})

    psi_values, reports = evaluate_data_drift(current, snapshot, psi_threshold=0.1)
    psi_value = psi_values["f1"]
    assert psi_value > 0
    assert reports[0].passed is (psi_value <= 0.1)

    _, reports_fail = evaluate_data_drift(current, snapshot, psi_threshold=psi_value - 1e-6)
    assert reports_fail[0].passed is False


def test_performance_gates_respect_thresholds():
    rng = pd.date_range("2024-01-01", periods=5, freq="D")
    rows = []
    for day, ts in enumerate(rng):
        for i in range(20):
            rows.append(
                {
                    "timestamp": ts + pd.Timedelta(hours=i),
                    "y_true": float(i % 2),
                    "y_pred": float(0.2 + 0.1 * day + 0.01 * i),
                }
            )
    df = pd.DataFrame(rows)

    metrics, reports = evaluate_performance_drift(
        df,
        window_days=3,
        pr_auc_threshold=0.0,
        brier_threshold=1.0,
    )

    assert not metrics.empty
    assert {r.name for r in reports} == {"performance.pr_auc", "performance.brier"}
    assert all(r.passed for r in reports)

    _, reports_fail = evaluate_performance_drift(
        df,
        window_days=3,
        pr_auc_threshold=0.99,
        brier_threshold=0.01,
    )
    assert any(not r.passed for r in reports_fail)
