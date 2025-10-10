import pytest

from app.execution.alpaca_orders import (
    build_bracket_limit_order,
    build_limit_order,
    build_market_order,
)


def test_limit_requires_price():
    with pytest.raises(ValueError):
        build_limit_order("AAPL", 1, "buy", None)


def test_bracket_limit_requires_price():
    with pytest.raises(ValueError):
        build_bracket_limit_order("AAPL", 1, "buy", None, 205.0, 195.0)


def test_market_ok_without_price():
    order = build_market_order("AAPL", 1, "buy")
    assert getattr(order, "symbol", "") == "AAPL"
