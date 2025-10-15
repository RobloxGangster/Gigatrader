from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

try:
    from backend.api import app  # uvicorn backend.api:app path
except Exception:  # pragma: no cover - fallback
    from backend.server import app  # type: ignore

from services.ml.registry import register_model


class IdentityCalibratedModel:
    def __init__(self) -> None:
        self.feature_names_in_ = np.array(["probability"], dtype=object)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        prob = np.clip(X[:, 0], 0.0, 1.0)
        return np.column_stack([1.0 - prob, prob])


def _write_parquet(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)


def test_ml_calibration_endpoint(tmp_path, monkeypatch):
    feature_store = tmp_path / "features"
    artifacts_dir = tmp_path / "artifacts"

    monkeypatch.setenv("FEATURE_STORE_PATH", str(feature_store))
    monkeypatch.setenv("ARTIFACTS_DIR", str(artifacts_dir))

    dates = pd.date_range("2024-01-01", periods=4, freq="D", tz="UTC")
    index = pd.MultiIndex.from_product([dates, ["AAPL"]], names=["timestamp", "symbol"])
    probabilities = [0.1, 0.4, 0.6, 0.8]
    targets = [0, 0, 1, 1]
    feature_frame = pd.DataFrame(
        {
            "probability": probabilities,
            "target": targets,
        },
        index=index,
    )
    _write_parquet(feature_store / "panel.parquet", feature_frame)

    model_name = "calibration_toy"
    register_model(model_name, IdentityCalibratedModel(), alias="production")

    client = TestClient(app)
    params = {
        "model": model_name,
        "alias": "production",
        "start": "2024-01-01T00:00:00Z",
        "end": "2024-01-04T23:59:59Z",
        "bins": 5,
        "symbols": "AAPL",
    }

    response = client.get("/ml/calibration", params=params)
    assert response.status_code == 200

    payload = response.json()
    assert payload["model_name"] == model_name
    assert payload["alias"] == "production"
    assert payload["brier_score"] == pytest.approx(0.0925, rel=1e-3)
    assert sum(payload["bin_counts"]) == 4
    assert payload["bin_mean_predicted"][0] == pytest.approx(0.1, rel=1e-3)
    assert payload["bin_observed_frequency"][0] == pytest.approx(0.0, abs=1e-3)
    assert payload["bin_mean_predicted"][2] == pytest.approx(0.5, rel=1e-3)
    assert payload["bin_observed_frequency"][2] == pytest.approx(0.5, rel=1e-3)
    assert payload["bin_mean_predicted"][4] == pytest.approx(0.8, rel=1e-3)
    assert payload["bin_observed_frequency"][4] == pytest.approx(1.0, rel=1e-3)


import pytest  # noqa: E402  - imported late for pytest.approx
