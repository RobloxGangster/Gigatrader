from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict

import numpy as np
import pandas as pd
try:
    from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
except ModuleNotFoundError:  # pragma: no cover - fallback when sklearn absent
    GradientBoostingClassifier = None
    RandomForestClassifier = None

try:  # pragma: no cover - optional dependency
    from xgboost import XGBClassifier  # type: ignore
except Exception:  # pragma: no cover
    XGBClassifier = None

from .models import LogisticRegression, SklearnModel, save_to_registry

logger = logging.getLogger(__name__)


@dataclass
class SelectionResult:
    model_key: str
    metrics: dict[str, float]
    sklearn_model: SklearnModel


CANDIDATES: Dict[str, Any] = {
    "lr": LogisticRegression(max_iter=500, class_weight="balanced"),
}
if RandomForestClassifier is not None:
    CANDIDATES["rf"] = RandomForestClassifier(n_estimators=50, max_depth=5, random_state=42)
if GradientBoostingClassifier is not None:
    CANDIDATES["gb"] = GradientBoostingClassifier(random_state=42)
if XGBClassifier is not None:
    CANDIDATES["xgb"] = XGBClassifier(
        n_estimators=50,
        max_depth=3,
        learning_rate=0.1,
        subsample=0.8,
        colsample_bytree=0.8,
        objective="binary:logistic",
        eval_metric="logloss",
        random_state=42,
    )


def evaluate_candidates(X: pd.DataFrame, y: pd.Series) -> SelectionResult:
    best_key = None
    best_auc = -np.inf
    best_metrics: dict[str, float] = {}
    best_model: SklearnModel | None = None

    for key, estimator in CANDIDATES.items():
        model = SklearnModel(estimator=estimator)
        model.fit(X, y)
        metrics = model.metrics or {}
        auc = metrics.get("auc", float("nan"))
        logger.info("Candidate %s metrics %s", key, metrics)
        if np.isnan(auc):
            auc = 0.0
        if auc > best_auc:
            best_auc = auc
            best_key = key
            best_metrics = metrics
            best_model = model

    if best_model is None or best_key is None:
        raise RuntimeError("No candidate models evaluated")

    save_to_registry(best_model)
    return SelectionResult(best_key, best_metrics, best_model)
