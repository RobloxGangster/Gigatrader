from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from backend.api import app
from services.backtest.v2 import BacktestV2Config, run_backtest_v2


def _make_synthetic_bars(rows: int = 90) -> pd.DataFrame:
    start = pd.Timestamp("2024-01-02 09:30")
    times = [start + pd.Timedelta(minutes=i) for i in range(rows)]
    trend = np.linspace(-0.5, 0.75, rows)
    oscillation = np.sin(np.linspace(0, 6.0, rows))
    close = 100 + np.cumsum(0.2 * oscillation + 0.05 * trend)
    open_ = np.concatenate(([close[0]], close[:-1]))
    high = np.maximum(open_, close) + 0.25
    low = np.minimum(open_, close) - 0.25
    signal = np.where(np.sin(np.linspace(0, 3.5, rows)) > 0, 1.0, -1.0)
    label = (np.roll(close, -1) > close).astype(int)
    label[-1] = int(label[-2])
    return pd.DataFrame(
        {
            "time": times,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "signal": signal,
            "label": label,
        }
    )


def test_backtest_v2_service_summary_keys():
    bars = _make_synthetic_bars()
    cfg = BacktestV2Config(n_splits=3, purge=1, embargo=1, daily_loss_limit=500.0, max_drawdown_limit=0.35)
    result = run_backtest_v2(bars, cfg)
    summary = result["summary"]
    for key in ("profit_factor", "sharpe", "pr_auc", "hit_rate", "max_drawdown"):
        assert key in summary
    assert result["artifacts"].get("equity_curve.csv")
    assert result["equity_curve"]


def test_backtest_v2_cli(tmp_path: Path):
    bars = _make_synthetic_bars()
    input_path = tmp_path / "bars.csv"
    bars.to_csv(input_path, index=False)
    artifact_dir = tmp_path / "artifacts"
    cmd = [
        sys.executable,
        "-m",
        "cli.backtest_v2",
        "--input",
        str(input_path),
        "--artifact-dir",
        str(artifact_dir),
        "--n-splits",
        "2",
    ]
    output = subprocess.check_output(cmd, text=True)
    payload = json.loads(output)
    assert {"config", "summary", "trades", "equity_curve", "artifacts"}.issubset(payload.keys())
    eq_path = Path(payload["artifacts"]["equity_curve.csv"])
    assert eq_path.exists()
    with eq_path.open() as fh:
        content = fh.read()
    assert "equity" in content


def test_backtest_v2_route_bundle():
    client = TestClient(app)
    bars = _make_synthetic_bars(60)
    payload_bars = []
    for row in bars.to_dict(orient="records"):
        row["time"] = pd.Timestamp(row["time"]).isoformat()
        payload_bars.append(row)
    response = client.post("/backtest_v2/", json={"bars": payload_bars})
    assert response.status_code == 200
    data = response.json()
    assert "summary" in data
    assert "artifacts" in data and "equity_curve.csv" in data["artifacts"]
    assert data["summary"]["trades"] >= 0
