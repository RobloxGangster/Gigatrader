from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.config import load_config


def test_live_requires_env(tmp_path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        "profile: live\n"
        "risk_profile: safe\n"
        "data:\n  symbols: []\n  timeframes: []\n  cache_path: data\n"
        "execution:\n  venue: alpaca\n  time_in_force: day\n"
        "risk_presets: {}\n"
    )
    os.environ.pop("LIVE_TRADING", None)
    with pytest.raises(ValueError):
        load_config(config)
