from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import numpy as np
import pandas as pd


def _safe(value: float, lo: float = -1e12, hi: float = 1e12) -> float:
    if not np.isfinite(value):
        return 0.0
    return float(min(max(value, lo), hi))


def _safe_ratio(num: float, den: float, default: float = 0.0) -> float:
    if abs(den) < 1e-12:
        return float(default)
    return float(num / den)


def _estimate_years(nbars: int, intraday_hint: bool) -> float:
    if nbars <= 0:
        return 1e-9
    if intraday_hint:
        return max(nbars / (252.0 * 390.0), 1e-9)
    return max(nbars / 252.0, 1e-9)


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
    initial_equity = float(max(notional, 1e-9))
    total_equity = initial_equity
    final_equity = initial_equity + net_pnl
    for row in df.itertuples():
        time_point = pd.to_datetime(row.time)
        if time_point < exit_time:
            total_equity = initial_equity
        else:
            total_equity = final_equity
        equity_curve.append({"time": time_point.isoformat(), "equity": float(total_equity)})

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

    equity_values = np.array([pt["equity"] for pt in equity_curve], dtype=float)
    equity_len = len(equity_values)
    intraday_hint = False
    if equity_len > 1:
        times = pd.Series(pd.to_datetime([row["time"] for row in equity_curve]))
        diffs = times.diff().dropna().dt.total_seconds()
        if not diffs.empty:
            intraday_hint = float(diffs.median()) < 18 * 3600

    if equity_len < 3 or initial_equity <= 0:
        stats = {
            "cagr": 0.0,
            "sharpe": 0.0,
            "max_dd": 0.0,
            "winrate": float(1.0 if net_pnl > 0 else 0.0),
            "avg_r": float(r_multiple) if not np.isnan(r_multiple) else 0.0,
            "avg_trade": float(net_pnl),
            "exposure": 0.0,
            "return_pct": float(return_pct),
        }
        return BacktestResult(trades=trades, equity_curve=equity_curve, stats=stats)

    years = _estimate_years(len(df), intraday_hint)
    try:
        growth = _safe_ratio(final_equity, initial_equity, default=1.0)
        if growth <= 0:
            cagr = 0.0
        else:
            cagr = (growth ** (1.0 / max(years, 1e-9))) - 1.0
    except Exception:
        cagr = 0.0
    cagr = _safe(cagr)

    returns = np.diff(equity_values)
    bases = np.maximum(equity_values[:-1], 1e-9)
    step_returns = np.divide(returns, bases, out=np.zeros_like(returns), where=bases != 0)
    annualization = 252 * 6.5 if intraday_hint else 252
    if len(step_returns) < 2:
        sharpe = 0.0
    else:
        mean_ret = float(np.mean(step_returns))
        std_ret = float(np.std(step_returns, ddof=1))
        if std_ret == 0:
            sharpe = 0.0
        else:
            sharpe = mean_ret / std_ret * np.sqrt(annualization)
    sharpe = _safe(sharpe)

    if equity_len:
        running_max = np.maximum.accumulate(equity_values)
        dd = (equity_values - running_max) / np.maximum(running_max, 1e-9)
        max_dd = float(dd.min()) if dd.size else 0.0
    else:
        max_dd = 0.0
    max_dd = _safe(max_dd)

    trading_minutes = max(len(df), 1)
    exposure = _safe_ratio((exit_time - entry_time).total_seconds() / 60.0, trading_minutes, default=0.0)

    stats = {
        "cagr": float(cagr),
        "sharpe": float(sharpe),
        "max_dd": float(max_dd),
        "winrate": float(1.0 if net_pnl > 0 else 0.0),
        "avg_r": float(r_multiple) if not np.isnan(r_multiple) else 0.0,
        "avg_trade": float(net_pnl),
        "exposure": float(_safe(exposure, lo=0.0)),
        "return_pct": float(_safe(return_pct)),
    }

    return BacktestResult(trades=trades, equity_curve=equity_curve, stats=stats)
