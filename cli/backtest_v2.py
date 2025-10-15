"""CLI for the bar-based backtest v2 runner."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from services.backtest.v2 import BacktestV2Config, run_backtest_v2


def _build_config(args: argparse.Namespace) -> BacktestV2Config:
    return BacktestV2Config(
        n_splits=args.n_splits,
        purge=args.purge,
        embargo=args.embargo,
        initial_capital=args.initial_capital,
        position_size=args.position_size,
        spread_bps=args.spread_bps,
        slippage_bps=args.slippage_bps,
        fee_per_unit=args.fee_per_unit,
        daily_loss_limit=args.daily_loss,
        max_drawdown_limit=args.max_drawdown,
        entry_threshold=args.entry_threshold,
        annualization_factor=args.annualization_factor,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the v2 backtest on a CSV dataset")
    parser.add_argument("--input", required=True, help="Path to a CSV file with bars and signals")
    parser.add_argument(
        "--artifact-dir",
        default="./artifacts",
        help="Directory where generated artifacts will be written",
    )
    parser.add_argument("--n-splits", type=int, default=3)
    parser.add_argument("--purge", type=int, default=0)
    parser.add_argument("--embargo", type=int, default=0)
    parser.add_argument("--initial-capital", type=float, default=100_000.0)
    parser.add_argument("--position-size", type=float, default=1.0)
    parser.add_argument("--spread-bps", type=float, default=1.0)
    parser.add_argument("--slippage-bps", type=float, default=1.0)
    parser.add_argument("--fee-per-unit", type=float, default=0.0)
    parser.add_argument("--daily-loss", type=float, default=None)
    parser.add_argument("--max-drawdown", type=float, default=None)
    parser.add_argument("--entry-threshold", type=float, default=0.0)
    parser.add_argument("--annualization-factor", type=float, default=252.0)
    args = parser.parse_args()

    df = pd.read_csv(args.input)
    config = _build_config(args)
    result = run_backtest_v2(df, config)

    artifact_dir = Path(args.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_paths: dict[str, str] = {}
    for name, data in result.get("artifacts", {}).items():
        path = artifact_dir / name
        path.write_text(data)
        artifact_paths[name] = str(path)

    output = dict(result)
    output["artifacts"] = artifact_paths
    print(json.dumps(output, indent=2, default=float))


if __name__ == "__main__":
    main()
