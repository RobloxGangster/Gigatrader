"""Lightweight bar-based backtest runner with purged CV support."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, Iterator, List, Tuple

import numpy as np
import pandas as pd
try:  # pragma: no cover - optional dependency
    from sklearn.metrics import average_precision_score  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - lightweight fallback
    def average_precision_score(y_true: np.ndarray, y_score: np.ndarray) -> float:
        """Compute a simple average precision score."""

        y_true = np.asarray(y_true, dtype=float)
        y_score = np.asarray(y_score, dtype=float)
        if y_true.size == 0:
            return 0.0
        order = np.argsort(-y_score)
        y_true_sorted = y_true[order]
        tp = np.cumsum(y_true_sorted)
        fp = np.cumsum(1.0 - y_true_sorted)
        total_positive = tp[-1] if tp.size else 0.0
        if total_positive <= 0:
            return 0.0
        precision = np.divide(tp, tp + fp, out=np.zeros_like(tp), where=(tp + fp) > 0)
        recall = tp / total_positive
        precision = np.concatenate(([precision[0] if precision.size else 0.0], precision))
        recall = np.concatenate(([0.0], recall))
        return float(np.sum((recall[1:] - recall[:-1]) * precision[1:]))


@dataclass(slots=True)
class BacktestV2Config:
    """Configuration for the bar-based backtest runner."""

    n_splits: int = 3
    purge: int = 0
    embargo: int = 0
    initial_capital: float = 100_000.0
    position_size: float = 1.0
    spread_bps: float = 1.0
    slippage_bps: float = 1.0
    fee_per_unit: float = 0.0
    daily_loss_limit: float | None = None
    max_drawdown_limit: float | None = None
    entry_threshold: float = 0.0
    annualization_factor: float = 252.0


@dataclass(slots=True)
class _FoldResult:
    equity_curve: List[Dict[str, float]]
    trades: List[Dict[str, float]]
    final_equity: float
    max_drawdown: float
    trading_stopped: bool


def _resolve_time_column(df: pd.DataFrame) -> str:
    for candidate in ("time", "timestamp", "datetime"):
        if candidate in df.columns:
            return candidate
    raise ValueError("bars dataframe must include a time-like column")


def _prepare_dataframe(bars: pd.DataFrame) -> pd.DataFrame:
    if bars.empty:
        raise ValueError("bars dataframe cannot be empty")
    df = bars.copy()
    time_col = _resolve_time_column(df)
    df[time_col] = pd.to_datetime(df[time_col])
    df = df.sort_values(time_col).reset_index(drop=True)
    if "signal" not in df.columns:
        raise ValueError("bars dataframe must include a 'signal' column")
    if "label" not in df.columns:
        next_close = df["close"].shift(-1)
        df["label"] = (next_close > df["close"]).astype(int)
    return df


def _purged_cv_indices(n: int, n_splits: int, purge: int, embargo: int) -> Iterator[Tuple[np.ndarray, np.ndarray]]:
    if n_splits <= 1 or n <= 1:
        yield np.arange(0, n, dtype=int), np.arange(0, n, dtype=int)
        return
    fold_sizes = [n // n_splits] * n_splits
    for i in range(n % n_splits):
        fold_sizes[i] += 1
    start = 0
    for fold_size in fold_sizes:
        end = start + fold_size
        test_idx = np.arange(start, end, dtype=int)
        train_mask = np.ones(n, dtype=bool)
        purge_lo = max(start - purge, 0)
        purge_hi = min(end + purge, n)
        train_mask[purge_lo:purge_hi] = False
        embargo_hi = min(end + embargo, n)
        train_mask[end:embargo_hi] = False
        train_idx = np.nonzero(train_mask)[0]
        yield train_idx, test_idx
        start = end


def _pessimistic_price(row: pd.Series, side: int, action: str, config: BacktestV2Config) -> float:
    assert action in {"entry", "exit"}
    close_price = float(row["close"])
    spread_component = close_price * (config.spread_bps / 2.0) / 1e4
    slippage_component = close_price * (config.slippage_bps / 1e4)
    adjust = spread_component + slippage_component
    if action == "entry":
        if side > 0:
            ref_price = float(row.get("high", close_price))
            price = ref_price + adjust
        else:
            ref_price = float(row.get("low", close_price))
            price = ref_price - adjust
    else:
        if side > 0:
            ref_price = float(row.get("low", close_price))
            price = ref_price - adjust
        else:
            ref_price = float(row.get("high", close_price))
            price = ref_price + adjust
    return float(max(price, 1e-8))


def _simulate_fold(
    df: pd.DataFrame,
    config: BacktestV2Config,
    initial_equity: float,
    time_col: str,
) -> _FoldResult:
    cash = float(initial_equity)
    position_units = 0.0
    entry_price: float | None = None
    entry_time: pd.Timestamp | None = None
    equity_curve: List[Dict[str, float]] = []
    trades: List[Dict[str, float]] = []
    peak_equity = float(initial_equity)
    max_drawdown = 0.0
    trading_stopped = False

    current_day: pd.Timestamp | None = None
    daily_loss = 0.0
    daily_stopped = False

    def close_position(row: pd.Series, ts: pd.Timestamp, reason: str) -> float:
        nonlocal cash, position_units, entry_price, entry_time, trades, daily_loss
        if position_units == 0.0 or entry_price is None or entry_time is None:
            return 0.0
        side = 1 if position_units > 0 else -1
        exit_price = _pessimistic_price(row, side, "exit", config)
        qty = abs(position_units)
        fees = config.fee_per_unit * qty
        cash += exit_price * position_units
        cash -= fees
        pnl = (exit_price - entry_price) * position_units
        net_pnl = pnl - fees
        trades.append(
            {
                "entry_time": entry_time.isoformat(),
                "exit_time": ts.isoformat(),
                "side": "long" if side > 0 else "short",
                "qty": float(qty),
                "entry_price": float(entry_price),
                "exit_price": float(exit_price),
                "pnl": float(net_pnl),
                "fees": float(fees),
                "reason": reason,
            }
        )
        daily_loss += float(net_pnl)
        position_units = 0.0
        entry_price = None
        entry_time = None
        return float(net_pnl)

    def open_position(row: pd.Series, ts: pd.Timestamp, target_units: float) -> None:
        nonlocal cash, position_units, entry_price, entry_time
        if abs(target_units) < 1e-12:
            return
        side = 1 if target_units > 0 else -1
        price = _pessimistic_price(row, side, "entry", config)
        qty = abs(target_units)
        fees = config.fee_per_unit * qty
        cash -= price * target_units
        cash -= fees
        position_units = float(target_units)
        entry_price = price
        entry_time = ts

    position_col = "position" if "position" in df.columns else None
    if position_col is not None and df[position_col].isna().all():
        position_col = None

    for idx, row in df.iterrows():
        ts = pd.to_datetime(row[time_col])
        day = ts.normalize()
        if current_day is None or day != current_day:
            current_day = day
            daily_loss = 0.0
            daily_stopped = False

        if position_col is not None:
            desired_raw = row[position_col]
            desired_units = float(desired_raw) if desired_raw is not None and not pd.isna(desired_raw) else 0.0
        else:
            signal = float(row["signal"])
            if signal > config.entry_threshold:
                desired_units = config.position_size
            elif signal < -config.entry_threshold:
                desired_units = -config.position_size
            else:
                desired_units = 0.0

        if daily_stopped:
            desired_units = 0.0

        if position_units != desired_units:
            if position_units != 0.0:
                close_position(row, ts, "signal_flip")
                if (
                    config.daily_loss_limit is not None
                    and daily_loss <= -abs(config.daily_loss_limit)
                ):
                    daily_stopped = True
                    desired_units = 0.0
            if desired_units != 0.0 and not daily_stopped:
                open_position(row, ts, desired_units)

        mark_price = float(row["close"])
        equity = cash + position_units * mark_price
        peak_equity = max(peak_equity, equity)
        if peak_equity > 0:
            drawdown = (peak_equity - equity) / peak_equity
        else:
            drawdown = 0.0
        max_drawdown = max(max_drawdown, drawdown)

        if (
            config.max_drawdown_limit is not None
            and drawdown >= abs(config.max_drawdown_limit)
        ):
            if position_units != 0.0:
                close_position(row, ts, "max_drawdown")
                equity = cash
            trading_stopped = True
            equity_curve.append({"time": ts.isoformat(), "equity": float(equity)})
            break

        if (
            config.daily_loss_limit is not None
            and daily_loss <= -abs(config.daily_loss_limit)
        ):
            daily_stopped = True
            if position_units != 0.0:
                close_position(row, ts, "daily_loss")
                equity = cash

        equity_curve.append({"time": ts.isoformat(), "equity": float(equity)})

    if not trading_stopped and position_units != 0.0:
        last_row = df.iloc[-1]
        ts = pd.to_datetime(last_row[time_col])
        close_position(last_row, ts, "end_of_data")
        equity_curve.append({"time": ts.isoformat(), "equity": float(cash)})

    return _FoldResult(
        equity_curve=equity_curve,
        trades=trades,
        final_equity=float(cash + position_units * float(df.iloc[-1]["close"]) if not trading_stopped else cash),
        max_drawdown=float(max_drawdown),
        trading_stopped=trading_stopped,
    )


def _combine_equity_curves(equity_rows: List[Dict[str, float]]) -> pd.DataFrame:
    if not equity_rows:
        return pd.DataFrame({"time": [], "equity": []})
    df = pd.DataFrame(equity_rows)
    df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values("time").drop_duplicates(subset=["time"], keep="last")
    return df.reset_index(drop=True)


def run_backtest_v2(bars: pd.DataFrame, config: BacktestV2Config | None = None) -> Dict[str, object]:
    """Run the pessimistic backtest and return summary metrics with artifacts."""

    cfg = config or BacktestV2Config()
    df = _prepare_dataframe(bars)
    time_col = _resolve_time_column(df)
    n = len(df)

    splits = list(_purged_cv_indices(n, cfg.n_splits, cfg.purge, cfg.embargo))
    equity_rows: List[Dict[str, float]] = []
    trades: List[Dict[str, float]] = []
    labels: List[np.ndarray] = []
    scores: List[np.ndarray] = []

    current_equity = cfg.initial_capital
    max_drawdown_observed = 0.0

    for _, test_idx in splits:
        if len(test_idx) == 0:
            continue
        test_df = df.iloc[test_idx].reset_index(drop=True)
        fold_res = _simulate_fold(test_df, cfg, current_equity, time_col)
        equity_rows.extend(fold_res.equity_curve)
        trades.extend(fold_res.trades)
        labels.append(test_df["label"].to_numpy(dtype=float))
        scores.append(test_df["signal"].to_numpy(dtype=float))
        current_equity = fold_res.final_equity
        max_drawdown_observed = max(max_drawdown_observed, fold_res.max_drawdown)
        if fold_res.trading_stopped:
            break

    equity_df = _combine_equity_curves(equity_rows)
    if equity_df.empty:
        equity_df = pd.DataFrame([
            {"time": pd.Timestamp(df[time_col].iloc[0]), "equity": float(cfg.initial_capital)}
        ])

    equity_series = equity_df["equity"].astype(float)
    returns = equity_series.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    sharpe = 0.0
    if not returns.empty and returns.std(ddof=0) > 1e-12:
        sharpe = float(np.sqrt(cfg.annualization_factor) * returns.mean() / returns.std(ddof=0))

    pnl_values = [trade["pnl"] for trade in trades]
    positive = sum(p for p in pnl_values if p > 0)
    negative = sum(p for p in pnl_values if p < 0)
    if negative == 0:
        profit_factor = float(positive) if positive > 0 else 0.0
    else:
        profit_factor = float(positive / abs(negative))

    hit_rate = float(sum(1 for p in pnl_values if p > 0) / len(pnl_values)) if pnl_values else 0.0

    if scores and labels:
        all_scores = np.concatenate(scores)
        all_labels = np.concatenate(labels)
        try:
            pr_auc = float(average_precision_score(all_labels, all_scores))
        except ValueError:
            pr_auc = 0.0
    else:
        pr_auc = 0.0

    equity_cummax = equity_series.cummax()
    drawdowns = (equity_cummax - equity_series) / equity_cummax.replace(0, np.nan)
    max_drawdown_series = float(drawdowns.max(skipna=True)) if not drawdowns.empty else 0.0
    max_drawdown_total = max(max_drawdown_observed, max_drawdown_series)

    total_return = float(equity_series.iloc[-1] / equity_series.iloc[0] - 1.0) if len(equity_series) > 1 else 0.0

    summary = {
        "initial_capital": float(cfg.initial_capital),
        "final_equity": float(equity_series.iloc[-1]),
        "total_return": total_return,
        "profit_factor": profit_factor,
        "sharpe": float(sharpe),
        "pr_auc": pr_auc,
        "hit_rate": hit_rate,
        "max_drawdown": float(max_drawdown_total),
        "trades": len(trades),
    }

    artifact_csv = equity_df.assign(time=equity_df["time"].dt.strftime("%Y-%m-%dT%H:%M:%S"))
    artifacts = {"equity_curve.csv": artifact_csv.to_csv(index=False)}

    equity_records = [
        {"time": pd.Timestamp(ts).isoformat(), "equity": float(eq)}
        for ts, eq in zip(equity_df["time"], equity_df["equity"])
    ]

    return {
        "config": asdict(cfg),
        "summary": summary,
        "trades": trades,
        "equity_curve": equity_records,
        "artifacts": artifacts,
    }
