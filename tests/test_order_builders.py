from __future__ import annotations

import pytest

from app.execution.alpaca_orders import build_bracket_limit_order, build_limit_order


def test_limit_order_requires_price():
    with pytest.raises(ValueError):
        build_limit_order("AAPL", 1, "buy", limit_price=None)  # type: ignore[arg-type]


def test_bracket_limit_requires_price():
    with pytest.raises(ValueError):
        build_bracket_limit_order(
            "AAPL",
            1,
            "buy",
            limit_price=None,
            take_profit_limit=200.0,
            stop_loss=190.0,  # type: ignore[arg-type]
        )
