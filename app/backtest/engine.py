from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import numpy as np
import pandas as pd


@dataclass
class BacktestResult:
    trades: list[dict]
    equity_curve: list[dict]
    stats: dict[str, float]


def _apply_slippage(price: float, side: Literal["buy", "sell"], slippage_bps: float, exit: bool = False) -> float:
    sign = 1 if side == "buy" else -1
    if exit:
        sign *= -1
    return price * (1 + sign * slippage_bps / 1e4)


def run_trade_backtest(
    bars: pd.DataFrame,
    entry: float,
    stop: float | None,
    target: float | None,
    side: Literal["buy", "sell"],
    slippage_bps: float = 1.0,
    commission_per_share: float = 0.005,
    time_exit: int | None = None,
    max_notional: float = 100_000.0,
) -> BacktestResult:
    if bars.empty:
        raise ValueError("bars dataframe cannot be empty")

    df = bars.sort_values("time").reset_index(drop=True)
    entry_time = pd.to_datetime(df["time"].iloc[0])
    exit_time = entry_time

    if stop is not None and stop == entry:
        stop = entry * (0.99 if side == "buy" else 1.01)

    risk_per_share = abs(entry - stop) if stop is not None else None
    if risk_per_share and risk_per_share > 0:
        qty = int(np.floor(1000 / risk_per_share))
    else:
        qty = int(np.floor(0.1 * max_notional / entry))
    qty = max(1, min(qty, int(max_notional / max(entry, 1e-6))))

    entry_exec = _apply_slippage(entry, side, slippage_bps, exit=False)
    notional = qty * entry_exec

    direction = 1 if side == "buy" else -1
    exit_price = df["close"].iloc[-1]
    exit_reason = "time"

    for idx in range(1, len(df)):
        row = df.iloc[idx]
        high = float(row["high"])
        low = float(row["low"])
        exit_time = pd.to_datetime(row["time"])
        stop_hit = False
        target_hit = False
        if side == "buy":
            if stop is not None and low <= stop:
                exit_price = stop
                exit_reason = "stop"
                stop_hit = True
            elif target is not None and high >= target:
                exit_price = target
                exit_reason = "target"
                target_hit = True
        else:
            if stop is not None and high >= stop:
                exit_price = stop
                exit_reason = "stop"
                stop_hit = True
            elif target is not None and low <= target:
                exit_price = target
                exit_reason = "target"
                target_hit = True
        if stop_hit or target_hit:
            break
        if time_exit is not None and idx >= time_exit:
            exit_price = float(row["close"])
            exit_reason = "time"
            break

    exit_exec = _apply_slippage(exit_price, side, slippage_bps, exit=True)
    pnl = direction * (exit_exec - entry_exec) * qty
    fees = commission_per_share * qty * 2
    net_pnl = pnl - fees
    r_multiple = (
        net_pnl / (abs(entry - stop) * qty) if stop is not None and abs(entry - stop) > 1e-9 else float("nan")
    )
    return_pct = net_pnl / max(notional, 1e-9)

    equity_curve = []
    cumulative = 0.0
    for row in df.itertuples():
        time_point = pd.to_datetime(row.time)
        if time_point <= exit_time:
            cumulative = net_pnl if time_point == exit_time else 0.0
        equity_curve.append({"time": time_point.isoformat(), "equity": float(cumulative)})

    trades = [
        {
            "symbol": "N/A",
            "entry_time": entry_time.isoformat(),
            "exit_time": exit_time.isoformat(),
            "side": side,
            "qty": float(qty),
            "entry_price": float(entry_exec),
            "exit_price": float(exit_exec),
            "pnl": float(net_pnl),
            "fees": float(fees),
            "reason": exit_reason,
            "r_multiple": float(r_multiple) if not np.isnan(r_multiple) else None,
        }
    ]

    duration_days = max((exit_time - entry_time).total_seconds() / 86400, 1 / 1440)
    annual_factor = 365 / duration_days
    cagr = float((1 + return_pct) ** annual_factor - 1)
    sharpe = float(return_pct / max(abs(return_pct), 1e-9) * np.sqrt(252))
    max_dd = min(0.0, min(np.cumsum([0, net_pnl])))
    exposure = float(duration_days / max(len(df) / 390, 1e-9))

    stats = {
        "cagr": float(cagr),
        "sharpe": float(sharpe),
        "max_dd": float(max_dd),
        "winrate": float(1.0 if net_pnl > 0 else 0.0),
        "avg_r": float(r_multiple) if not np.isnan(r_multiple) else 0.0,
        "avg_trade": float(net_pnl),
        "exposure": float(exposure),
        "return_pct": float(return_pct),
    }

    return BacktestResult(trades=trades, equity_curve=equity_curve, stats=stats)
