from __future__ import annotations

from pathlib import Path

import pandas as pd

from services.options.adapter import (
    MAX_SPREAD_BPS,
    MIN_OPEN_INTEREST,
    get_option_chain,
)


def test_mock_adapter_filters_liquidity(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "true")
    artifacts_root = Path(__file__).resolve().parent / "artifacts"
    monkeypatch.setenv("ARTIFACTS_DIR", str(artifacts_root))

    chain = get_option_chain("SPY", "2023-08-01")
    assert not chain.empty

    # Liquidity filters enforced
    assert (chain["oi"] >= MIN_OPEN_INTEREST).all()
    spreads = (chain["ask"] - chain["bid"]) / chain["mid"] * 10_000
    assert (spreads <= MAX_SPREAD_BPS).all()

    # Only weekly/monthly Friday expiries remain
    assert chain["expiry"].dt.dayofweek.eq(4).all()

    # Should preserve both call and put at the ATM strike
    assert set(chain["side"]) == {"call", "put"}
    assert pd.api.types.is_datetime64_any_dtype(chain["expiry"])
