from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, Iterable, Tuple, List
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss
from .registry import register_model


@dataclass
class WFConfig:
    model_name: str
    horizon_bars: int
    train_days: int
    step_days: int
    start: str
    end: str
    symbol_universe: List[str]


def _split_walk_forward(dates: pd.DatetimeIndex, start: datetime, end: datetime,
                        train_days: int, step_days: int) -> Iterable[Tuple[pd.Timestamp, pd.Timestamp]]:
    cur = start + timedelta(days=train_days)
    while cur <= end:
        yield (cur - timedelta(days=train_days), cur)
        cur += timedelta(days=step_days)


def _build_model():
    base = HistGradientBoostingClassifier(max_depth=6, learning_rate=0.05, max_iter=400)
    return CalibratedClassifierCV(base, method="isotonic", cv=3)


def _metrics(y_true: np.ndarray, proba: np.ndarray) -> Dict[str, float]:
    return {
        "auc": float(roc_auc_score(y_true, proba)),
        "pr_auc": float(average_precision_score(y_true, proba)),
        "brier": float(brier_score_loss(y_true, proba))
    }


def _load_features(symbols: List[str], start: str, end: str) -> pd.DataFrame:
    """
    Connect here to your feature store (the same data feeding /ml/features).
    CONTRACT: MultiIndex (datetime, symbol), columns=[feature..., 'target'] with 0/1 target.
    """
    from services.data.features_loader import load_feature_panel

    return load_feature_panel(symbols, start, end)


def train_walk_forward(cfg: WFConfig) -> Dict[str, Any]:
    df = _load_features(cfg.symbol_universe, cfg.start, cfg.end).sort_index()
    times = df.index.get_level_values(0)
    start_dt = pd.to_datetime(cfg.start)
    end_dt = pd.to_datetime(cfg.end)

    tz = getattr(times, "tz", None)
    if tz is not None:
        if start_dt.tzinfo is None:
            start_dt = start_dt.tz_localize(tz)
        else:
            start_dt = start_dt.tz_convert(tz)
        if end_dt.tzinfo is None:
            end_dt = end_dt.tz_localize(tz)
        else:
            end_dt = end_dt.tz_convert(tz)

    folds = []
    feature_cols = [c for c in df.columns if c != "target"]

    for tr_start, split_point in _split_walk_forward(times, start_dt, end_dt, cfg.train_days, cfg.step_days):
        tr_mask = (times >= tr_start) & (times < split_point)
        te_mask = (times >= split_point) & (times < (split_point + timedelta(days=cfg.step_days)))
        if tr_mask.sum() < 200 or te_mask.sum() < 50:
            continue

        X_tr = df.loc[tr_mask, feature_cols].to_numpy()
        y_tr = df.loc[tr_mask, "target"].to_numpy().astype(int)
        X_te = df.loc[te_mask, feature_cols].to_numpy()
        y_te = df.loc[te_mask, "target"].to_numpy().astype(int)

        model = _build_model()
        model.fit(X_tr, y_tr)
        import numpy as _np
        setattr(model, "feature_names_in_", _np.array(feature_cols))
        proba = model.predict_proba(X_te)[:, 1]
        m = _metrics(y_te, proba)
        folds.append({"split_point": split_point.isoformat(), "metrics": m, "model": model})

    if not folds:
        raise RuntimeError("No valid folds created. Check date range and data availability.")

    best = max(folds, key=lambda f: f["metrics"]["pr_auc"])
    meta = register_model(cfg.model_name, best["model"], metrics=best["metrics"], tags={
        "cfg": cfg.__dict__, "selected_split": best["split_point"]
    }, alias="production")

    return {
        "registered": meta.__dict__,
        "folds": [{"split_point": f["split_point"], **f["metrics"]} for f in folds]
    }
