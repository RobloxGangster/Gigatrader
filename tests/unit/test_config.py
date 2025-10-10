from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.config import load_config


def test_live_requires_env(tmp_path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        "{"  # JSON subset keeps the loader dependency-free
        '"profile": "live",'
        '"risk_profile": "safe",'
        '"data": {"symbols": [], "timeframes": [], "cache_path": "data"},'
        '"execution": {"venue": "alpaca", "time_in_force": "day"},'
        '"risk_presets": {}'
        "}"
    )
    os.environ.pop("LIVE_TRADING", None)
    with pytest.raises(ValueError):
        load_config(config)
