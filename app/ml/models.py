from __future__ import annotations

try:
    import joblib
except ModuleNotFoundError:  # pragma: no cover - fallback for minimal envs
    import pickle

    class _Joblib:
        @staticmethod
        def dump(obj, path):
            with open(path, "wb") as handle:
                pickle.dump(obj, handle)

        @staticmethod
        def load(path):
            with open(path, "rb") as handle:
                return pickle.load(handle)

    joblib = _Joblib()

import copy
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, roc_auc_score
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - lightweight fallback
    SKLEARN_AVAILABLE = False

    def accuracy_score(y_true, y_pred):
        y_true = np.asarray(y_true)
        y_pred = np.asarray(y_pred)
        return float((np.round(y_pred) == y_true).mean())

    def roc_auc_score(y_true, y_score):
        y_true = np.asarray(y_true)
        y_score = np.asarray(y_score)
        pos = y_score[y_true == 1]
        neg = y_score[y_true == 0]
        if len(pos) == 0 or len(neg) == 0:
            return float("nan")
        wins = (pos[:, None] > neg).sum()
        ties = (pos[:, None] == neg).sum()
        return float((wins + 0.5 * ties) / (len(pos) * len(neg)))

    class StandardScaler:
        def __init__(self) -> None:
            self.mean_: np.ndarray | None = None
            self.scale_: np.ndarray | None = None

        def fit(self, X: np.ndarray, y: np.ndarray | None = None) -> "StandardScaler":
            X = np.asarray(X, dtype=float)
            self.mean_ = X.mean(axis=0)
            self.scale_ = X.std(axis=0)
            self.scale_[self.scale_ == 0] = 1.0
            return self

        def transform(self, X: np.ndarray) -> np.ndarray:
            X = np.asarray(X, dtype=float)
            return (X - self.mean_) / self.scale_

        def fit_transform(self, X: np.ndarray, y: np.ndarray | None = None) -> np.ndarray:
            return self.fit(X, y).transform(X)

    class LogisticRegression:
        def __init__(self, max_iter: int = 500, class_weight: str | None = None, learning_rate: float = 0.1) -> None:
            self.max_iter = max_iter
            self.learning_rate = learning_rate
            self.coef_: np.ndarray | None = None
            self.intercept_: float = 0.0

        def fit(self, X: np.ndarray, y: np.ndarray) -> "LogisticRegression":
            X = np.asarray(X, dtype=float)
            y = np.asarray(y, dtype=float)
            self.coef_ = np.zeros(X.shape[1], dtype=float)
            self.intercept_ = 0.0
            for _ in range(self.max_iter):
                logits = X @ self.coef_ + self.intercept_
                probs = 1.0 / (1.0 + np.exp(-logits))
                error = probs - y
                grad_w = X.T @ error / len(X)
                grad_b = error.mean()
                self.coef_ -= self.learning_rate * grad_w
                self.intercept_ -= self.learning_rate * grad_b
            return self

        def predict_proba(self, X: np.ndarray) -> np.ndarray:
            X = np.asarray(X, dtype=float)
            logits = X @ self.coef_ + self.intercept_
            probs = 1.0 / (1.0 + np.exp(-logits))
            return np.column_stack([1 - probs, probs])

    class Pipeline:
        def __init__(self, steps: list[tuple[str, Any]]) -> None:
            self.steps = steps
            self._transformers: list[tuple[str, Any]] = []
            self._estimator: Any | None = None

        def fit(self, X: np.ndarray, y: np.ndarray) -> "Pipeline":
            data = np.asarray(X, dtype=float)
            self._transformers = []
            for name, step in self.steps[:-1]:
                if hasattr(step, "fit_transform"):
                    data = step.fit_transform(data, y)
                else:
                    data = step.fit(data, y).transform(data)
                self._transformers.append((name, step))
            self._estimator = self.steps[-1][1]
            self._estimator.fit(data, y)
            return self

        def predict_proba(self, X: np.ndarray) -> np.ndarray:
            data = np.asarray(X, dtype=float)
            for _, step in self._transformers:
                data = step.transform(data)
            return self._estimator.predict_proba(data)

    class CalibratedClassifierCV:
        def __init__(self, estimator: Pipeline, method: str = "sigmoid", cv: str | int = "prefit") -> None:
            self.base_estimator = estimator

        def fit(self, X: np.ndarray, y: np.ndarray) -> "CalibratedClassifierCV":
            self.base_estimator.fit(X, y)
            return self

        def predict_proba(self, X: np.ndarray) -> np.ndarray:
            return self.base_estimator.predict_proba(X)

from .features import FEATURE_LIST

logger = logging.getLogger(__name__)

REGISTRY_DIR = Path("artifacts/registry")
REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_MODEL_NAME = "intraday_lr"


@dataclass
class SklearnModel:
    estimator: Any = field(default_factory=lambda: LogisticRegression(max_iter=500, class_weight="balanced"))
    metrics: dict[str, float] | None = None
    created_at: datetime | None = None
    _clf: Any | None = field(default=None, init=False, repr=False)
    _calibrated: bool = field(default=False, init=False, repr=False)

    def _prepare_X(self, X_df: pd.DataFrame) -> pd.DataFrame:
        X_df = X_df.copy()
        missing = [c for c in FEATURE_LIST if c not in X_df.columns]
        for col in missing:
            X_df[col] = 0.0
        return X_df[FEATURE_LIST]

    def fit(self, X_df: pd.DataFrame, y: pd.Series) -> "SklearnModel":
        if len(X_df) != len(y):
            raise ValueError("Feature and label length mismatch")

        X_df = self._prepare_X(X_df)
        y = y.reset_index(drop=True)

        n_samples = len(X_df)
        if n_samples == 0:
            raise ValueError("No samples provided")

        split_idx = int(n_samples * 0.8)
        val_len = n_samples - split_idx
        if val_len <= 0:
            split_idx = int(n_samples * 0.9)
            val_len = n_samples - split_idx

        if val_len <= 0:
            X_train, y_train = X_df, y
            X_val: pd.DataFrame | None = None
            y_val: pd.Series | None = None
        else:
            X_train, X_val = X_df.iloc[:split_idx], X_df.iloc[split_idx:]
            y_train, y_val = y.iloc[:split_idx], y.iloc[split_idx:]

        estimator_clone = copy.deepcopy(self.estimator)
        pipeline = Pipeline([
            ("scaler", StandardScaler()),
            ("estimator", estimator_clone),
        ])

        X_train_np = X_train.to_numpy(dtype=float)
        y_train_np = y_train.to_numpy(dtype=float)
        pipeline.fit(X_train_np, y_train_np)

        clf: Any = pipeline
        calibrated = False

        if X_val is not None and y_val is not None and not X_val.empty:
            y_val_np = y_val.to_numpy(dtype=float)
            if len(np.unique(y_val_np)) > 1:
                calibrator = CalibratedClassifierCV(estimator=pipeline, method="sigmoid", cv="prefit")
                calibrator.fit(X_val.to_numpy(dtype=float), y_val_np)
                clf = calibrator
                calibrated = True

        self._clf = clf
        self._calibrated = calibrated

        eval_X = X_val if X_val is not None and not X_val.empty else X_train
        eval_y = y_val if y_val is not None and not y_val.empty else y_train
        eval_X_np = eval_X.to_numpy(dtype=float)
        eval_y_np = eval_y.to_numpy(dtype=float)

        try:
            proba = clf.predict_proba(eval_X_np)[:, 1]
        except Exception:
            # pragma: no cover - compatibility for stub implementations
            proba = np.zeros(len(eval_X_np), dtype=float)

        unique_labels = np.unique(eval_y_np)
        if unique_labels.size > 1:
            auc = roc_auc_score(eval_y_np, proba)
        else:
            auc = float("nan")
        preds = (proba >= 0.5).astype(int)
        acc = accuracy_score(eval_y_np, preds)

        self.metrics = {
            "auc": float(auc),
            "accuracy": float(acc),
            "samples": float(n_samples),
            "calibrated": float(1.0 if calibrated else 0.0),
        }
        self.created_at = datetime.utcnow()
        return self

    @property
    def calibrated_model(self) -> Any | None:  # backwards compatibility for older callers
        return self._clf

    @calibrated_model.setter
    def calibrated_model(self, value: Any | None) -> None:
        self._clf = value
        self._calibrated = bool(value is not None)

    def predict_proba(self, X_df: pd.DataFrame) -> float | list[float]:
        if self._clf is None:
            raise RuntimeError("Model not fitted")
        prepared = self._prepare_X(X_df)
        proba = self._clf.predict_proba(prepared.to_numpy(dtype=float))
        up = proba[:, 1]
        if len(up) == 1:
            return float(up.tolist()[0])
        return [float(v) for v in up.tolist()]

    def save(self, path: Path) -> None:
        if self._clf is None:
            raise RuntimeError("Nothing to save")
        artifact = {
            "feature_list": FEATURE_LIST,
            "model": self._clf,
            "metrics": self.metrics or {},
            "created_at": self.created_at or datetime.utcnow(),
            "calibrated": bool(self._calibrated),
        }
        joblib.dump(artifact, path)

    @classmethod
    def load(cls, path: Path) -> "SklearnModel":
        data = joblib.load(path)
        model = cls()
        model._clf = data["model"]
        model._calibrated = bool(data.get("calibrated", False))
        model.metrics = {k: float(v) for k, v in data.get("metrics", {}).items()}
        created = data.get("created_at")
        if isinstance(created, datetime):
            model.created_at = created
        else:
            try:
                model.created_at = datetime.fromisoformat(str(created))
            except Exception:  # pragma: no cover
                model.created_at = datetime.utcnow()
        return model


def save_to_registry(model: SklearnModel, name: str = DEFAULT_MODEL_NAME) -> Path:
    path = REGISTRY_DIR / f"{name}.joblib"
    model.save(path)
    logger.info("Saved model to %s", path)
    return path


def load_from_registry(name: str = DEFAULT_MODEL_NAME) -> SklearnModel | None:
    path = REGISTRY_DIR / f"{name}.joblib"
    if not path.exists():
        return None
    return SklearnModel.load(path)
