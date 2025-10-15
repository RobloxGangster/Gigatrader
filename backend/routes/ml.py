from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any
from services.ml.registry import load_model, list_models

router = APIRouter(prefix="/ml", tags=["ml"])


class PredictItem(BaseModel):
    symbol: str
    features: Dict[str, float]


class PredictRequest(BaseModel):
    model_name: str = Field(..., description="Model family to load from registry")
    version: Optional[str] = None
    alias: Optional[str] = "production"
    items: List[PredictItem]


class PredictResponseItem(BaseModel):
    symbol: str
    proba_up: float


class PredictResponse(BaseModel):
    model_name: str
    resolved_version: str
    predictions: List[PredictResponseItem]


@router.get("/status")
def ml_status() -> Dict[str, Any]:
    return {"registry": list_models()}


@router.post("/predict", response_model=PredictResponse)
def ml_predict(req: PredictRequest):
    try:
        model = load_model(req.model_name, version=req.version, alias=req.alias)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    feat_order = getattr(model, "feature_names_in_", None)
    X = []
    for it in req.items:
        if feat_order is not None:
            row = [it.features.get(k, 0.0) for k in feat_order]
        else:
            row = [it.features[k] for k in sorted(it.features.keys())]
        X.append(row)

    import numpy as np
    X = np.asarray(X)
    try:
        proba = model.predict_proba(X)[:, 1]
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Inference failed: {e!s}")

    resolved = req.version or f"alias:{req.alias or 'production'}"
    return PredictResponse(
        model_name=req.model_name,
        resolved_version=resolved,
        predictions=[PredictResponseItem(symbol=it.symbol, proba_up=float(p))
                     for it, p in zip(req.items, proba)]
    )
