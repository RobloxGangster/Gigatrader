from __future__ import annotations

from typing import List

import numpy as np
from fastapi import APIRouter, HTTPException, Query

from services.data.features_loader import load_feature_panel
from services.ml.registry import get_model_meta, load_model

router = APIRouter(prefix="/ml", tags=["ml"])


@router.get("/calibration")
def ml_calibration(
    model: str = Query(..., description="Model family to load from registry"),
    alias: str = Query("production", description="Alias within the model registry"),
    bins: int = Query(10, ge=1, le=200, description="Number of probability bins"),
    start: str = Query(..., description="Start timestamp (inclusive)"),
    end: str = Query(..., description="End timestamp (inclusive)"),
    symbols: List[str] | None = Query(None, description="Symbols to include (comma separated or repeated)"),
):
    # Resolve the list of symbols, supporting comma-separated values provided by Streamlit inputs.
    resolved_symbols: List[str]
    if symbols:
        resolved_symbols = []
        for entry in symbols:
            if entry:
                resolved_symbols.extend(s.strip() for s in entry.split(",") if s.strip())
    else:
        resolved_symbols = []

    try:
        meta = get_model_meta(model, alias=alias)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        model_obj = load_model(model, version=meta.version)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        feature_panel = load_feature_panel(resolved_symbols, start, end)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if feature_panel.empty:
        raise HTTPException(status_code=404, detail="No feature data available for the requested window.")

    if "target" not in feature_panel.columns:
        raise HTTPException(status_code=400, detail="Feature panel is missing the 'target' column.")

    y_true = feature_panel["target"].to_numpy(dtype=float)
    feature_matrix = feature_panel.drop(columns=["target"]).copy()

    feature_order = getattr(model_obj, "feature_names_in_", None)
    if feature_order is not None:
        missing = [name for name in feature_order if name not in feature_matrix.columns]
        if missing:
            raise HTTPException(status_code=400, detail=f"Missing features required by model: {missing}")
        X = feature_matrix.loc[:, list(feature_order)].to_numpy(dtype=float)
    else:
        X = feature_matrix.to_numpy(dtype=float)

    try:
        proba = np.asarray(model_obj.predict_proba(X), dtype=float)
    except Exception as exc:  # pragma: no cover - model specific failure
        raise HTTPException(status_code=400, detail=f"Model inference failed: {exc}") from exc

    if proba.ndim != 2 or proba.shape[1] < 2:
        raise HTTPException(status_code=400, detail="Model must return class probabilities with two columns.")

    p_up = proba[:, 1]
    if p_up.shape[0] != y_true.shape[0]:
        raise HTTPException(status_code=400, detail="Prediction and target lengths do not match.")

    brier = float(np.mean((p_up - y_true) ** 2))

    edges = np.linspace(0.0, 1.0, bins + 1)
    counts: List[int] = []
    mean_pred: List[float | None] = []
    observed_freq: List[float | None] = []

    for idx in range(len(edges) - 1):
        lower = edges[idx]
        upper = edges[idx + 1]
        if idx == len(edges) - 2:
            mask = (p_up >= lower) & (p_up <= upper)
        else:
            mask = (p_up >= lower) & (p_up < upper)
        count = int(np.count_nonzero(mask))
        counts.append(count)
        if count:
            mean_pred.append(float(p_up[mask].mean()))
            observed_freq.append(float(y_true[mask].mean()))
        else:
            mean_pred.append(None)
            observed_freq.append(None)

    response = {
        "model_name": model,
        "resolved_version": meta.version,
        "alias": alias,
        "start": start,
        "end": end,
        "n_samples": int(y_true.shape[0]),
        "brier_score": brier,
        "bin_edges": [float(edge) for edge in edges],
        "bin_mean_predicted": mean_pred,
        "bin_observed_frequency": observed_freq,
        "bin_counts": counts,
    }

    if resolved_symbols:
        response["symbols"] = resolved_symbols

    return response
