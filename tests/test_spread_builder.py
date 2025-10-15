"""Unit tests for spread construction utilities."""

from __future__ import annotations

import pytest

from services.options.chain import OptionContract
from services.options.spread_builder import (
    SpreadPlan,
    build_credit_put_spread,
    build_debit_call_spread,
)


def _contract(
    *,
    symbol: str,
    side: str,
    strike: float,
    delta: float,
    bid: float,
    ask: float,
    oi: int = 500,
    volume: int = 400,
    expiry: str = "2025-01-17",
) -> OptionContract:
    return OptionContract(
        symbol=symbol,
        underlying="AAPL",
        expiry=expiry,
        strike=strike,
        side=side,  # type: ignore[arg-type]
        delta=delta,
        iv=0.4,
        bid=bid,
        ask=ask,
        mid=(bid + ask) / 2,
        volume=volume,
        oi=oi,
        dte=45,
        raw={"greeks": {"vega": 0.12, "theta": -0.04}},
    )


_CONFIG = {
    "options_max_notional_per_expiry": 10_000.0,
    "min_option_liquidity": 50,
    "delta_bounds": (0.1, 0.6),
    "vega_limit": 1.5,
    "theta_limit": 1.0,
}


def test_build_debit_call_spread_returns_expected_structure() -> None:
    long_call = _contract(symbol="AAPL_C_150", side="call", strike=150.0, delta=0.35, bid=5.4, ask=5.6)
    short_call = _contract(symbol="AAPL_C_155", side="call", strike=155.0, delta=0.22, bid=2.9, ask=3.1)

    plan = build_debit_call_spread(long_call, short_call, _CONFIG)

    assert isinstance(plan, SpreadPlan)
    payload = plan.as_dict()
    assert payload["name"] == "debit_call"
    assert pytest.approx(payload["pricing"]["net_debit"], rel=1e-6) == pytest.approx(2.7)
    assert payload["pricing"]["max_loss"] > 0
    assert payload["pricing"]["max_profit"] > 0
    assert payload["risk"]["caps"]["max_notional"] == _CONFIG["options_max_notional_per_expiry"]
    assert payload["risk"]["delta"] is not None
    assert len(payload["legs"]) == 2
    assert payload["legs"][0]["action"] == "buy"
    assert payload["legs"][1]["action"] == "sell"


def test_credit_put_spread_enforces_guardrails() -> None:
    short_put = _contract(symbol="AAPL_P_150", side="put", strike=150.0, delta=-0.35, bid=5.6, ask=5.8)
    long_put = _contract(symbol="AAPL_P_140", side="put", strike=140.0, delta=-0.18, bid=1.2, ask=1.4)

    plan = build_credit_put_spread(short_put, long_put, _CONFIG)
    assert plan.as_dict()["pricing"]["net_credit"] > 0

    illiquid_long = _contract(
        symbol="AAPL_P_130",
        side="put",
        strike=130.0,
        delta=-0.1,
        bid=0.5,
        ask=0.7,
        oi=10,
        volume=10,
    )

    with pytest.raises(ValueError):
        build_credit_put_spread(short_put, illiquid_long, _CONFIG)


def test_guardrail_rejects_notional_limit() -> None:
    long_call = _contract(symbol="AAPL_C_190", side="call", strike=190.0, delta=0.52, bid=18.0, ask=18.5)
    short_call = _contract(symbol="AAPL_C_200", side="call", strike=200.0, delta=0.48, bid=17.5, ask=17.7)

    high_cost_config = dict(_CONFIG)
    high_cost_config["options_max_notional_per_expiry"] = 50.0

    with pytest.raises(ValueError):
        build_debit_call_spread(long_call, short_call, high_cost_config)
