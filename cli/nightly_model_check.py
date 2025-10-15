import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

import pandas as pd

from services.ml.drift import evaluate_data_drift, evaluate_performance_drift, GateReport
from services.ml.registry import get_model_meta, promote_alias
from services.ml.walkforward import WFConfig, train_walk_forward


def _load_frame(path: str) -> pd.DataFrame:
    suffix = Path(path).suffix.lower()
    if suffix in {".csv", ".txt"}:
        return pd.read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if suffix == ".json":
        return pd.read_json(path)
    raise ValueError(f"Unsupported file format for {path}")


def _print_reports(title: str, reports: Iterable[GateReport]) -> None:
    reports_list = list(reports)
    print(f"=== {title} ===")
    for report in reports_list:
        status = "PASS" if report.passed else "FAIL"
        print(
            f"[{status}] {report.name}: value={report.value:.6f} "
            f"threshold={report.threshold:.6f}"
        )
    if not reports_list:
        print("No guardrails evaluated.")


def _load_retrain_cfg(path: str) -> WFConfig:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return WFConfig(**data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Nightly drift and performance checks.")
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--model-alias", default="production", help="Alias to evaluate (default: production)")
    parser.add_argument("--features-path", required=True, help="Current feature snapshot data (csv/parquet/json)")
    parser.add_argument("--predictions-path", required=True, help="Predictions with realised outcomes")
    parser.add_argument("--psi-threshold", type=float, default=0.2)
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument("--pr-auc-threshold", type=float, default=0.4)
    parser.add_argument("--brier-threshold", type=float, default=0.25)
    parser.add_argument("--timestamp-col", default="timestamp")
    parser.add_argument("--target-col", default="y_true")
    parser.add_argument("--proba-col", default="y_pred")
    parser.add_argument("--retrain-config", help="JSON file describing WFConfig for retraining")
    parser.add_argument("--staging-alias", default="staging")
    parser.add_argument("--promote", action="store_true", help="Promote staging alias to production when guardrails pass")
    args = parser.parse_args(argv)

    try:
        meta = get_model_meta(args.model_name, alias=args.model_alias)
    except FileNotFoundError as exc:  # pragma: no cover - defensive logging
        print(str(exc), file=sys.stderr)
        return 1

    snapshot = meta.tags.get("drift_snapshot")
    if not snapshot:
        print("Model registry entry missing drift snapshot; re-train model with updated pipeline.", file=sys.stderr)
        return 1

    try:
        feature_df = _load_frame(args.features_path)
        predictions_df = _load_frame(args.predictions_path)
    except Exception as exc:  # pragma: no cover - IO errors
        print(f"Failed to load inputs: {exc}", file=sys.stderr)
        return 1

    psi_values, data_reports = evaluate_data_drift(feature_df, snapshot, psi_threshold=args.psi_threshold)
    print("--- Data Drift (PSI) ---")
    for feature, value in sorted(psi_values.items()):
        status = "PASS" if value <= args.psi_threshold else "FAIL"
        print(f"{feature}: PSI={value:.6f} (threshold={args.psi_threshold:.6f}) -> {status}")
    metrics, perf_reports = evaluate_performance_drift(
        predictions_df,
        window_days=args.window_days,
        pr_auc_threshold=args.pr_auc_threshold,
        brier_threshold=args.brier_threshold,
        timestamp_col=args.timestamp_col,
        target_col=args.target_col,
        proba_col=args.proba_col,
    )

    print("--- Performance Drift ---")
    _print_reports("Rolling metrics", perf_reports)

    if not metrics.empty:
        latest = metrics.iloc[-1]
        print(
            "Latest rolling window: date={date} pr_auc={pr:.6f} brier={brier:.6f}".format(
                date=latest["date"],
                pr=latest["pr_auc_roll"],
                brier=latest["brier_roll"],
            )
        )

    all_reports = list(data_reports) + list(perf_reports)
    overall_pass = all(report.passed for report in all_reports)
    print(f"Overall gate status: {'PASS' if overall_pass else 'FAIL'}")

    if not overall_pass:
        return 2

    if args.retrain_config:
        cfg = _load_retrain_cfg(args.retrain_config)
        print("Retraining via walk-forward ...")
        result = train_walk_forward(cfg, alias=args.staging_alias)
        print(
            "Registered staging model version {version} with PR-AUC={pr:.6f}.".format(
                version=result["registered"]["version"],
                pr=result["registered"]["metrics"].get("pr_auc", float("nan")),
            )
        )

    if args.promote:
        try:
            staging_meta = get_model_meta(args.model_name, alias=args.staging_alias)
        except FileNotFoundError as exc:  # pragma: no cover
            print(f"Cannot promote staging alias: {exc}", file=sys.stderr)
            return 3
        promote_alias(args.model_name, staging_meta.version, alias="production")
        print(f"Promoted version {staging_meta.version} to production")

    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
