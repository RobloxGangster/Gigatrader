"""Backtest metrics calculations."""

from __future__ import annotations

import numpy as np


def cagr(equity_curve: list[float], periods_per_year: int = 252) -> float:
    if not equity_curve:
        return 0.0
    total_return = equity_curve[-1]
    years = len(equity_curve) / periods_per_year
    if years == 0:
        return 0.0
    return (1 + total_return) ** (1 / years) - 1


def sharpe_ratio(returns: list[float], risk_free: float = 0.0) -> float:
    if not returns:
        return 0.0
    excess = np.array(returns) - risk_free
    if excess.std() == 0:
        return 0.0
    return (excess.mean() / excess.std()) * np.sqrt(252)
