"""Tests for option contract selection logic."""

from __future__ import annotations

from services.options.chain import OptionContract
from services.options.select import select_contract


def _contract(
    delta: float,
    dte: int,
    *,
    oi: int = 1000,
    volume: int = 500,
    mid: float = 2.5,
    side: str = "call",
) -> OptionContract:
    return OptionContract(
        symbol=f"S{delta}_{dte}",
        underlying="AAPL",
        expiry="2025-01-01",
        strike=100.0,
        side=side,  # type: ignore[arg-type]
        delta=delta,
        iv=0.4,
        bid=mid - 0.1,
        ask=mid + 0.1,
        mid=mid,
        volume=volume,
        oi=oi,
        dte=dte,
    )


def test_select_prefers_closest_delta_then_nearest_dte_then_volume() -> None:
    candidates = [
        _contract(0.28, 14, volume=300),
        _contract(0.31, 10, volume=200),
        _contract(0.305, 10, volume=100),
        _contract(0.29, 20, volume=1000),
    ]
    selected = select_contract(candidates, "call", 0.30, 0.05, 50, 50, 7, 45, 50.0)
    assert selected is not None
    assert selected.symbol.startswith("S0.305_10")


def test_filters_by_liquidity_dte_and_price() -> None:
    candidates = [
        _contract(0.30, 3),
        _contract(0.30, 10, mid=60.0),
        _contract(0.30, 15, oi=10),
        _contract(0.30, 20, volume=5),
    ]
    selected = select_contract(candidates, "call", 0.30, 0.05, 50, 50, 7, 45, 50.0)
    assert selected is None
