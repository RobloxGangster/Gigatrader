from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from services.ml.walkforward import WFConfig, train_walk_forward


def _write_feature_store(path: Path, df: pd.DataFrame) -> None:
    path.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path / "part.parquet")


def test_train_walk_forward_smoke(tmp_path, monkeypatch):
    store_path = tmp_path / "feature_store"
    artifacts_path = tmp_path / "artifacts"

    dates = pd.date_range(
        "2024-01-01", "2024-01-04 23:55", freq="5min", tz="UTC"
    )
    symbols = ["AAPL"]
    index = pd.MultiIndex.from_product([dates, symbols], names=["timestamp", "symbol"])

    rng = np.random.default_rng(0)
    df = pd.DataFrame(
        {
            "feat1": rng.normal(size=len(index)),
            "feat2": rng.normal(size=len(index)),
            "target": rng.integers(0, 2, size=len(index)),
        },
        index=index,
    )

    _write_feature_store(store_path, df)

    monkeypatch.setenv("FEATURE_STORE_PATH", str(store_path))
    monkeypatch.setenv("ARTIFACTS_DIR", str(artifacts_path))

    cfg = WFConfig(
        model_name="smoke_model",
        horizon_bars=5,
        train_days=1,
        step_days=1,
        start="2024-01-01",
        end="2024-01-04",
        symbol_universe=["AAPL"],
    )

    result = train_walk_forward(cfg)

    assert "registered" in result
    assert "folds" in result
    assert result["folds"], "Expected at least one fold to be returned"
    for fold in result["folds"]:
        for metric in ("auc", "pr_auc", "brier"):
            assert metric in fold

    assert artifacts_path.exists()
    assert any(p.suffix == ".joblib" for p in artifacts_path.rglob("*.joblib"))
    registry_file = artifacts_path / "registry.json"
    assert registry_file.exists()
